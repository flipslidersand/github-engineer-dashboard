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
	key := "activity:" + strings.ToLower(username)

	var cached model.UserActivity
	if d.Cache.Get(key, &cached) {
		cached.Cached = true
		writeJSON(w, http.StatusOK, cached)
		return
	}

	client := newClient(r, d)
	data, err := client.GetUserActivity(username)
	if err != nil {
		writeGitHubError(w, err)
		return
	}
	_ = d.Cache.Set(key, data)
	writeJSON(w, http.StatusOK, data)
}

func (d *Deps) analyze(w http.ResponseWriter, r *http.Request) {
	rawURL := r.URL.Query().Get("url")
	if rawURL == "" {
		writeError(w, http.StatusUnprocessableEntity, "url query parameter required")
		return
	}

	parsed := parseGitHubURL(rawURL)
	client := newClient(r, d)

	switch parsed.typ {
	case urlTypeUser:
		username := parsed.username
		key := "activity:" + strings.ToLower(username)
		var cached model.UserActivity
		if d.Cache.Get(key, &cached) {
			cached.Cached = true
			writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "user", URL: rawURL, Data: cached})
			return
		}
		data, err := client.GetUserActivity(username)
		if err != nil {
			writeGitHubError(w, err)
			return
		}
		_ = d.Cache.Set(key, data)
		writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "user", URL: rawURL, Data: data})

	case urlTypeRepo:
		key := fmt.Sprintf("repo:%s/%s", strings.ToLower(parsed.username), strings.ToLower(parsed.repo))
		var cached model.RepoInfo
		if d.Cache.Get(key, &cached) {
			cached.Cached = true
			writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "repo", URL: rawURL, Data: cached})
			return
		}
		data, err := client.GetRepo(parsed.username, parsed.repo)
		if err != nil {
			writeGitHubError(w, err)
			return
		}
		_ = d.Cache.Set(key, data)
		writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "repo", URL: rawURL, Data: data})

	case urlTypePR:
		key := fmt.Sprintf("pr:%s/%s/%d",
			strings.ToLower(parsed.username), strings.ToLower(parsed.repo), parsed.number)
		var cached model.PRInfo
		if d.Cache.Get(key, &cached) {
			cached.Cached = true
			writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "pr", URL: rawURL, Data: cached})
			return
		}
		data, err := client.GetPR(parsed.username, parsed.repo, parsed.number)
		if err != nil {
			writeGitHubError(w, err)
			return
		}
		_ = d.Cache.Set(key, data)
		writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "pr", URL: rawURL, Data: data})

	case urlTypeIssue:
		key := fmt.Sprintf("issue:%s/%s/%d",
			strings.ToLower(parsed.username), strings.ToLower(parsed.repo), parsed.number)
		var cached model.IssueInfo
		if d.Cache.Get(key, &cached) {
			cached.Cached = true
			writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "issue", URL: rawURL, Data: cached})
			return
		}
		data, err := client.GetIssue(parsed.username, parsed.repo, parsed.number)
		if err != nil {
			writeGitHubError(w, err)
			return
		}
		_ = d.Cache.Set(key, data)
		writeJSON(w, http.StatusOK, model.AnalyzeResult{Type: "issue", URL: rawURL, Data: data})

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

	var (
		ownerKey string
		data     *model.CrossRepoSummary
		err      error
	)

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
	var cached model.CrossRepoSummary
	if d.Cache.Get(key, &cached) {
		cached.Cached = true
		writeJSON(w, http.StatusOK, cached)
		return
	}

	if parsed.typ == urlTypeUser {
		data, err = client.GetUserReposSummary(parsed.username, excludeForks)
	} else {
		data, err = client.GetOrgReposSummary(parsed.org, excludeForks)
	}
	if err != nil {
		writeGitHubError(w, err)
		return
	}
	_ = d.Cache.Set(key, data)
	writeJSON(w, http.StatusOK, data)
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
