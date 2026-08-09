// Package handler registers all HTTP routes for the dashboard API.
package handler

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/flipslidersand/github-engineer-dashboard/backend-go/internal/cache"
	gh "github.com/flipslidersand/github-engineer-dashboard/backend-go/internal/github"
	"github.com/flipslidersand/github-engineer-dashboard/backend-go/internal/model"
)

const version = "0.1.0"

// Deps holds shared dependencies injected into each handler.
type Deps struct {
	Cache        *cache.Cache
	GithubToken  string
	GithubAPIURL string
}

// Register mounts all routes on r.
func Register(r chi.Router, d *Deps) {
	r.Get("/healthz", d.healthz)
	r.Get("/api/rate-limit", d.requireToken(d.rateLimit))
	r.Get("/api/users/{username}/activity", d.requireToken(d.userActivity))
	r.Get("/api/analyze", d.requireToken(d.analyze))
	r.Get("/api/summary", d.requireToken(d.summary))
}

// ── middleware ────────────────────────────────────────────────────────────────

func (d *Deps) requireToken(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token := r.Header.Get("X-GitHub-Token")
		if token == "" {
			token = d.GithubToken
		}
		if token == "" {
			writeError(w, http.StatusUnauthorized,
				"GitHub token required. Provide the 'X-GitHub-Token' header.")
			return
		}
		// Store token in request context via chi's context helpers isn't needed;
		// handlers call newClient(r, d) which resolves the token.
		r.Header.Set("X-GitHub-Token", token) // normalise for newClient
		next(w, r)
	}
}

func newClient(r *http.Request, d *Deps) *gh.Client {
	token := r.Header.Get("X-GitHub-Token")
	if token == "" {
		token = d.GithubToken
	}
	return gh.New(token, d.GithubAPIURL)
}

// ── handlers ─────────────────────────────────────────────────────────────────

func (d *Deps) healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, model.Health{Status: "ok", Version: version})
}

func (d *Deps) rateLimit(w http.ResponseWriter, r *http.Request) {
	client := newClient(r, d)
	rl, err := client.GetRateLimit()
	if err != nil {
		writeGitHubError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rl)
}

func (d *Deps) userActivity(w http.ResponseWriter, r *http.Request) {
	username := chi.URLParam(r, "username")
	client := newClient(r, d)
	v, cached, err := fromCache(d.Cache, "activity:"+strings.ToLower(username),
		func() (*model.UserActivity, error) { return client.GetUserActivity(username) })
	if err != nil {
		writeGitHubError(w, err)
		return
	}
	v.Cached = cached
	writeJSON(w, http.StatusOK, v)
}

func (d *Deps) analyze(w http.ResponseWriter, r *http.Request) {
	rawURL := r.URL.Query().Get("url")
	if rawURL == "" {
		writeError(w, http.StatusUnprocessableEntity, "url query parameter required")
		return
	}

	parsed := parseGitHubURL(rawURL)
	client := newClient(r, d)

	writeAnalyze := func(typ string, v any, wasCached bool, err error) {
		if err != nil {
			writeGitHubError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: typ, URL: rawURL, Data: v})
	}

	switch parsed.typ {
	case urlTypeUser:
		u := parsed.username
		v, cached, err := fromCache(d.Cache, "activity:"+strings.ToLower(u),
			func() (*model.UserActivity, error) { return client.GetUserActivity(u) })
		if err == nil {
			v.Cached = cached
		}
		writeAnalyze("user", v, cached, err)

	case urlTypeRepo:
		u, repo := parsed.username, parsed.repo
		key := fmt.Sprintf("repo:%s/%s", strings.ToLower(u), strings.ToLower(repo))
		v, cached, err := fromCache(d.Cache, key,
			func() (*model.RepoInfo, error) { return client.GetRepo(u, repo) })
		if err == nil {
			v.Cached = cached
		}
		writeAnalyze("repo", v, cached, err)

	case urlTypePR:
		u, repo, num := parsed.username, parsed.repo, parsed.number
		key := fmt.Sprintf("pr:%s/%s/%d", strings.ToLower(u), strings.ToLower(repo), num)
		v, cached, err := fromCache(d.Cache, key,
			func() (*model.PRInfo, error) { return client.GetPR(u, repo, num) })
		if err == nil {
			v.Cached = cached
		}
		writeAnalyze("pr", v, cached, err)

	case urlTypeIssue:
		u, repo, num := parsed.username, parsed.repo, parsed.number
		key := fmt.Sprintf("issue:%s/%s/%d", strings.ToLower(u), strings.ToLower(repo), num)
		v, cached, err := fromCache(d.Cache, key,
			func() (*model.IssueInfo, error) { return client.GetIssue(u, repo, num) })
		if err == nil {
			v.Cached = cached
		}
		writeAnalyze("issue", v, cached, err)

	default:
		writeError(w, http.StatusUnprocessableEntity,
			"Unsupported URL. Provide a GitHub user, repository, PR, or issue URL.")
	}
}

func (d *Deps) summary(w http.ResponseWriter, r *http.Request) {
	rawURL := r.URL.Query().Get("url")
	excludeForks := r.URL.Query().Get("exclude_forks") == "true"

	parsed := parseGitHubURL(rawURL)
	client := newClient(r, d)

	var ownerKey string
	switch parsed.typ {
	case urlTypeUser:
		ownerKey = "user:" + strings.ToLower(parsed.username)
	case urlTypeOrg:
		ownerKey = "org:" + strings.ToLower(parsed.org)
	default:
		writeError(w, http.StatusUnprocessableEntity,
			"Summary requires a GitHub user or organization URL.")
		return
	}

	key := fmt.Sprintf("summary:%s:forks=%d", ownerKey, boolToInt(excludeForks))
	var fetchFn func() (*model.CrossRepoSummary, error)
	if parsed.typ == urlTypeUser {
		fetchFn = func() (*model.CrossRepoSummary, error) {
			return client.GetUserReposSummary(parsed.username, excludeForks)
		}
	} else {
		fetchFn = func() (*model.CrossRepoSummary, error) {
			return client.GetOrgReposSummary(parsed.org, excludeForks)
		}
	}

	v, cached, err := fromCache(d.Cache, key, fetchFn)
	if err != nil {
		writeGitHubError(w, err)
		return
	}
	v.Cached = cached
	writeJSON(w, http.StatusOK, v)
}

// ── URL parser ────────────────────────────────────────────────────────────────

type urlType int

const (
	urlTypeUnknown urlType = iota
	urlTypeUser
	urlTypeOrg
	urlTypeRepo
	urlTypePR
	urlTypeIssue
)

type parsedURL struct {
	typ      urlType
	username string
	org      string
	repo     string
	number   int
}

func parseGitHubURL(raw string) parsedURL {
	if !strings.HasPrefix(raw, "http://") && !strings.HasPrefix(raw, "https://") {
		raw = "https://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil {
		return parsedURL{typ: urlTypeUnknown}
	}
	host := strings.ToLower(u.Hostname())
	if host != "github.com" && host != "www.github.com" {
		return parsedURL{typ: urlTypeUnknown}
	}

	var parts []string
	for _, p := range strings.Split(u.Path, "/") {
		if p != "" {
			parts = append(parts, p)
		}
	}

	if len(parts) >= 2 && parts[0] == "orgs" {
		return parsedURL{typ: urlTypeOrg, org: parts[1]}
	}
	if len(parts) == 1 {
		return parsedURL{typ: urlTypeUser, username: parts[0]}
	}
	if len(parts) >= 4 {
		n, err := strconv.Atoi(parts[3])
		if err == nil {
			switch parts[2] {
			case "pull":
				return parsedURL{typ: urlTypePR, username: parts[0], repo: parts[1], number: n}
			case "issues":
				return parsedURL{typ: urlTypeIssue, username: parts[0], repo: parts[1], number: n}
			}
		}
	}
	if len(parts) >= 2 {
		return parsedURL{typ: urlTypeRepo, username: parts[0], repo: parts[1]}
	}
	return parsedURL{typ: urlTypeUnknown}
}

// ── cache helper ──────────────────────────────────────────────────────────────

// fromCache returns cached data (wasCached=true) or calls fetch, stores result,
// and returns fresh data (wasCached=false). On fetch error returns nil, false, err.
func fromCache[T any](c *cache.Cache, key string, fetch func() (*T, error)) (*T, bool, error) {
	var dst T
	if c.Get(key, &dst) {
		return &dst, true, nil
	}
	v, err := fetch()
	if err != nil {
		return nil, false, err
	}
	_ = c.Set(key, v)
	return v, false, nil
}

// ── helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func writeGitHubError(w http.ResponseWriter, err error) {
	var e *gh.Error
	if ghErr, ok := err.(*gh.Error); ok {
		e = ghErr
		status := e.StatusCode
		if status == 403 {
			status = 429
		}
		writeError(w, status, e.Message)
		return
	}
	writeError(w, http.StatusBadGateway, err.Error())
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}
