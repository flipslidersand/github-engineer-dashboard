// Package github provides a thin GitHub REST API v3 client.
package github

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/flipslidersand/github-engineer-dashboard/backend-go/internal/model"
)

const (
	defaultBaseURL  = "https://api.github.com"
	reposPageSize   = 100
	reposMaxPages   = 10
)

// Error is returned when GitHub responds with a non-2xx status.
type Error struct {
	StatusCode int
	Message    string
}

func (e *Error) Error() string {
	return fmt.Sprintf("GitHub API error %d: %s", e.StatusCode, e.Message)
}

// Client holds the HTTP client and auth credentials.
type Client struct {
	token      string
	baseURL    string
	httpClient *http.Client
}

// New creates a Client. If baseURL is empty, the public GitHub API is used.
func New(token, baseURL string) *Client {
	if baseURL == "" {
		baseURL = defaultBaseURL
	}
	return &Client{
		token:      token,
		baseURL:    strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
}

// get issues a GET request and returns the response body, or a *Error.
func (c *Client) get(path string) ([]byte, error) {
	return c.getWithAccept(path, "application/vnd.github+json")
}

func (c *Client) getWithAccept(path, accept string) ([]byte, error) {
	req, err := http.NewRequest(http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", accept)
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode >= 400 {
		var msg struct {
			Message string `json:"message"`
		}
		if json.Unmarshal(body, &msg) == nil && msg.Message != "" {
			return nil, &Error{StatusCode: resp.StatusCode, Message: msg.Message}
		}
		return nil, &Error{StatusCode: resp.StatusCode, Message: string(body)}
	}
	return body, nil
}

// tryGet fetches path and unmarshals into dst; returns false on any error.
func (c *Client) tryGet(path string, dst any) bool {
	data, err := c.get(path)
	if err != nil {
		return false
	}
	return json.Unmarshal(data, dst) == nil
}

// GetRateLimit returns the core rate-limit block.
func (c *Client) GetRateLimit() (*model.RateLimit, error) {
	data, err := c.get("/rate_limit")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Resources struct {
			Core model.RateLimit `json:"core"`
		} `json:"resources"`
	}
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, err
	}
	return &resp.Resources.Core, nil
}

// GetUserActivity aggregates a user's profile, events, and repo stats.
func (c *Client) GetUserActivity(username string) (*model.UserActivity, error) {
	type ghUser struct {
		Login       string  `json:"login"`
		Name        *string `json:"name"`
		Bio         *string `json:"bio"`
		Location    *string `json:"location"`
		Company     *string `json:"company"`
		Blog        string  `json:"blog"`
		CreatedAt   string  `json:"created_at"`
		PublicRepos int     `json:"public_repos"`
		Followers   int     `json:"followers"`
		Following   int     `json:"following"`
	}
	type ghEvent struct {
		Type string `json:"type"`
	}
	type ghRepo struct {
		Name            string  `json:"name"`
		FullName        string  `json:"full_name"`
		StargazersCount int     `json:"stargazers_count"`
		Language        *string `json:"language"`
		Fork            bool    `json:"fork"`
		UpdatedAt       string  `json:"updated_at"`
	}

	var (
		user      ghUser
		events    []ghEvent
		repos     []ghRepo
		userErr   error
		eventsErr error
		wg        sync.WaitGroup
	)

	wg.Add(3)
	go func() {
		defer wg.Done()
		data, err := c.get("/users/" + username)
		if err != nil {
			userErr = err
			return
		}
		userErr = json.Unmarshal(data, &user)
	}()
	go func() {
		defer wg.Done()
		data, err := c.get("/users/" + username + "/events/public")
		if err != nil {
			eventsErr = err
			return
		}
		eventsErr = json.Unmarshal(data, &events)
	}()
	go func() {
		defer wg.Done()
		c.tryGet("/users/"+username+"/repos?per_page=100", &repos)
	}()
	wg.Wait()

	if userErr != nil {
		return nil, userErr
	}
	if eventsErr != nil {
		return nil, eventsErr
	}

	eventCounts := map[string]int{}
	for _, e := range events {
		t := e.Type
		if t == "" {
			t = "Unknown"
		}
		eventCounts[t]++
	}

	langCounts := map[string]int{}
	totalStars := 0
	var recentForks []model.RecentFork
	for _, r := range repos {
		if !r.Fork {
			totalStars += r.StargazersCount
			if r.Language != nil && *r.Language != "" {
				langCounts[*r.Language]++
			}
		} else {
			recentForks = append(recentForks, model.RecentFork{
				Name:      r.Name,
				FullName:  r.FullName,
				Stars:     r.StargazersCount,
				UpdatedAt: r.UpdatedAt,
			})
		}
	}
	sort.Slice(recentForks, func(i, j int) bool {
		return recentForks[i].UpdatedAt > recentForks[j].UpdatedAt
	})
	if len(recentForks) > 3 {
		recentForks = recentForks[:3]
	}

	repoLanguages := topN(langCounts, 8)

	var blog *string
	if user.Blog != "" {
		blog = &user.Blog
	}

	return &model.UserActivity{
		Username:      user.Login,
		Name:          user.Name,
		Bio:           user.Bio,
		Location:      user.Location,
		Company:       user.Company,
		Blog:          blog,
		CreatedAt:     &user.CreatedAt,
		PublicRepos:   user.PublicRepos,
		Followers:     user.Followers,
		Following:     user.Following,
		TotalStars:    totalStars,
		EventCounts:   eventCounts,
		TotalEvents:   len(events),
		RepoLanguages: repoLanguages,
		RecentForks:   orEmpty(recentForks),
	}, nil
}

// GetRepo returns structured data for a repository.
func (c *Client) GetRepo(username, repo string) (*model.RepoInfo, error) {
	type ghRepo struct {
		Owner           struct{ Login string `json:"login"` } `json:"owner"`
		Name            string   `json:"name"`
		FullName        string   `json:"full_name"`
		Description     *string  `json:"description"`
		StargazersCount int      `json:"stargazers_count"`
		ForksCount      int      `json:"forks_count"`
		OpenIssuesCount int      `json:"open_issues_count"`
		Language        *string  `json:"language"`
		License         *struct {
			SPDXID string `json:"spdx_id"`
			Name   string `json:"name"`
		} `json:"license"`
		Topics    []string `json:"topics"`
		UpdatedAt string   `json:"updated_at"`
	}

	data, err := c.get(fmt.Sprintf("/repos/%s/%s", username, repo))
	if err != nil {
		return nil, err
	}
	var r ghRepo
	if err := json.Unmarshal(data, &r); err != nil {
		return nil, err
	}

	base := fmt.Sprintf("/repos/%s/%s", username, repo)

	type ghContributor struct {
		Login         string `json:"login"`
		Contributions int    `json:"contributions"`
		AvatarURL     string `json:"avatar_url"`
	}
	type ghRelease struct {
		TagName     string `json:"tag_name"`
		PublishedAt string `json:"published_at"`
	}
	type ghParticipation struct {
		All []int `json:"all"`
	}

	var (
		rawContribs   []ghContributor
		languages     map[string]int
		openPRs       []json.RawMessage
		release       ghRelease
		participation ghParticipation
		wg            sync.WaitGroup
	)

	wg.Add(5)
	go func() { defer wg.Done(); c.tryGet(base+"/contributors?per_page=5", &rawContribs) }()
	go func() { defer wg.Done(); c.tryGet(base+"/languages", &languages) }()
	go func() { defer wg.Done(); c.tryGet(base+"/pulls?state=open&per_page=100", &openPRs) }()
	go func() { defer wg.Done(); c.tryGet(base+"/releases/latest", &release) }()
	go func() { defer wg.Done(); c.tryGet(base+"/stats/participation", &participation) }()
	wg.Wait()

	contributors := make([]model.Contributor, 0, len(rawContribs))
	for _, c := range rawContribs {
		contributors = append(contributors, model.Contributor{
			Username:      c.Login,
			Contributions: c.Contributions,
			AvatarURL:     c.AvatarURL,
		})
	}

	openPRCount := len(openPRs)

	var latestRelease, latestReleaseAt *string
	if release.TagName != "" {
		latestRelease = &release.TagName
		latestReleaseAt = &release.PublishedAt
	}

	var commitsLast30d *int
	if len(participation.All) >= 4 {
		sum := 0
		for _, v := range participation.All[len(participation.All)-4:] {
			sum += v
		}
		commitsLast30d = &sum
	}

	var licenseStr *string
	if r.License != nil {
		s := r.License.SPDXID
		if s == "" {
			s = r.License.Name
		}
		if s != "" {
			licenseStr = &s
		}
	}

	if languages == nil {
		languages = map[string]int{}
	}

	return &model.RepoInfo{
		Owner:           r.Owner.Login,
		Name:            r.Name,
		FullName:        r.FullName,
		Description:     r.Description,
		Stars:           r.StargazersCount,
		Forks:           r.ForksCount,
		OpenIssues:      r.OpenIssuesCount,
		OpenPRCount:     openPRCount,
		Language:        r.Language,
		License:         licenseStr,
		Topics:          orEmpty(r.Topics),
		UpdatedAt:       r.UpdatedAt,
		Contributors:    contributors,
		Languages:       languages,
		LatestRelease:   latestRelease,
		LatestReleaseAt: latestReleaseAt,
		CommitsLast30d:  commitsLast30d,
	}, nil
}

// GetPR returns structured data for a pull request.
func (c *Client) GetPR(username, repo string, number int) (*model.PRInfo, error) {
	type ghPR struct {
		Number        int     `json:"number"`
		Title         string  `json:"title"`
		State         string  `json:"state"`
		User          struct{ Login string `json:"login"` } `json:"user"`
		Base          struct{ Ref string `json:"ref"` } `json:"base"`
		Head          struct{ Ref string `json:"ref"` } `json:"head"`
		Additions     int     `json:"additions"`
		Deletions     int     `json:"deletions"`
		ChangedFiles  int     `json:"changed_files"`
		Comments      int     `json:"comments"`
		ReviewComments int    `json:"review_comments"`
		CreatedAt     string  `json:"created_at"`
		MergedAt      *string `json:"merged_at"`
	}
	type ghReview struct {
		User        struct{ Login string `json:"login"` } `json:"user"`
		SubmittedAt string `json:"submitted_at"`
	}
	type ghFile struct {
		Filename  string `json:"filename"`
		Additions int    `json:"additions"`
		Deletions int    `json:"deletions"`
	}

	base := fmt.Sprintf("/repos/%s/%s/pulls/%d", username, repo, number)

	var (
		prData  []byte
		reviews []ghReview
		files   []ghFile
		prErr   error
		wg      sync.WaitGroup
	)
	wg.Add(3)
	go func() { defer wg.Done(); prData, prErr = c.get(base) }()
	go func() { defer wg.Done(); c.tryGet(base+"/reviews", &reviews) }()
	go func() { defer wg.Done(); c.tryGet(base+"/files?per_page=30", &files) }()
	wg.Wait()

	if prErr != nil {
		return nil, prErr
	}
	var pr ghPR
	if err := json.Unmarshal(prData, &pr); err != nil {
		return nil, err
	}

	reviewerSet := map[string]bool{}
	for _, rv := range reviews {
		if rv.User.Login != "" {
			reviewerSet[rv.User.Login] = true
		}
	}
	reviewers := make([]string, 0, len(reviewerSet))
	for u := range reviewerSet {
		reviewers = append(reviewers, u)
	}

	var reviewWaitHours *float64
	var earliest string
	for _, rv := range reviews {
		if rv.SubmittedAt != "" && (earliest == "" || rv.SubmittedAt < earliest) {
			earliest = rv.SubmittedAt
		}
	}
	if earliest != "" {
		created, err1 := time.Parse(time.RFC3339, pr.CreatedAt)
		reviewed, err2 := time.Parse(time.RFC3339, earliest)
		if err1 == nil && err2 == nil {
			h := math.Round(reviewed.Sub(created).Hours()*10) / 10
			reviewWaitHours = &h
		}
	}

	changedFilesDetail := make([]model.ChangedFile, 0, len(files))
	for _, f := range files {
		changedFilesDetail = append(changedFilesDetail, model.ChangedFile{
			Filename:  f.Filename,
			Additions: f.Additions,
			Deletions: f.Deletions,
		})
	}

	state := pr.State
	if pr.MergedAt != nil {
		state = "merged"
	}

	return &model.PRInfo{
		Number:             pr.Number,
		Title:              pr.Title,
		State:              state,
		Author:             pr.User.Login,
		Base:               pr.Base.Ref,
		Head:               pr.Head.Ref,
		Additions:          pr.Additions,
		Deletions:          pr.Deletions,
		ChangedFiles:       pr.ChangedFiles,
		Comments:           pr.Comments,
		ReviewComments:     pr.ReviewComments,
		Reviewers:          reviewers,
		ReviewWaitHours:    reviewWaitHours,
		ChangedFilesDetail: changedFilesDetail,
		CreatedAt:          pr.CreatedAt,
		MergedAt:           pr.MergedAt,
	}, nil
}

// GetPRDiff returns the raw unified diff for a pull request.
func (c *Client) GetPRDiff(username, repo string, number int) (string, error) {
	path := fmt.Sprintf("/repos/%s/%s/pulls/%d", username, repo, number)
	data, err := c.getWithAccept(path, "application/vnd.github.v3.diff")
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// GetIssue returns structured data for an issue.
func (c *Client) GetIssue(username, repo string, number int) (*model.IssueInfo, error) {
	type ghIssue struct {
		Number    int     `json:"number"`
		Title     string  `json:"title"`
		State     string  `json:"state"`
		User      struct{ Login string `json:"login"` } `json:"user"`
		Labels    []struct{ Name string `json:"name"` } `json:"labels"`
		Assignees []struct{ Login string `json:"login"` } `json:"assignees"`
		Comments  int     `json:"comments"`
		CreatedAt string  `json:"created_at"`
		ClosedAt  *string `json:"closed_at"`
	}
	type ghTimelineEvent struct {
		Event  string `json:"event"`
		Source struct {
			Issue struct {
				Number      int `json:"number"`
				PullRequest any `json:"pull_request"`
			} `json:"issue"`
		} `json:"source"`
	}

	base := fmt.Sprintf("/repos/%s/%s/issues/%d", username, repo, number)

	data, err := c.get(base)
	if err != nil {
		return nil, err
	}
	var issue ghIssue
	if err := json.Unmarshal(data, &issue); err != nil {
		return nil, err
	}

	var timeline []ghTimelineEvent
	c.tryGet(base+"/timeline?per_page=100", &timeline)

	relatedSet := map[int]bool{}
	for _, e := range timeline {
		if e.Event == "cross-referenced" && e.Source.Issue.PullRequest != nil {
			relatedSet[e.Source.Issue.Number] = true
		}
	}
	relatedPRs := make([]int, 0, len(relatedSet))
	for n := range relatedSet {
		relatedPRs = append(relatedPRs, n)
	}

	labels := make([]string, 0, len(issue.Labels))
	for _, l := range issue.Labels {
		labels = append(labels, l.Name)
	}
	assignees := make([]string, 0, len(issue.Assignees))
	for _, a := range issue.Assignees {
		assignees = append(assignees, a.Login)
	}

	return &model.IssueInfo{
		Number:     issue.Number,
		Title:      issue.Title,
		State:      issue.State,
		Author:     issue.User.Login,
		Labels:     labels,
		Assignees:  assignees,
		Comments:   issue.Comments,
		RelatedPRs: relatedPRs,
		CreatedAt:  issue.CreatedAt,
		ClosedAt:   issue.ClosedAt,
	}, nil
}

// GetUserReposSummary aggregates a user's repos.
func (c *Client) GetUserReposSummary(username string, excludeForks bool) (*model.CrossRepoSummary, error) {
	data, truncated, err := c.aggregateRepoList("/users/"+username+"/repos", excludeForks)
	if err != nil {
		return nil, err
	}
	data.Owner = username
	data.OwnerType = "user"
	data.Truncated = truncated
	return data, nil
}

// GetOrgReposSummary aggregates an org's repos.
func (c *Client) GetOrgReposSummary(org string, excludeForks bool) (*model.CrossRepoSummary, error) {
	data, truncated, err := c.aggregateRepoList("/orgs/"+org+"/repos", excludeForks)
	if err != nil {
		return nil, err
	}
	data.Owner = org
	data.OwnerType = "org"
	data.Truncated = truncated
	return data, nil
}

func (c *Client) aggregateRepoList(basePath string, excludeForks bool) (*model.CrossRepoSummary, bool, error) {
	type ghRepo struct {
		StargazersCount int     `json:"stargazers_count"`
		ForksCount      int     `json:"forks_count"`
		Language        *string `json:"language"`
		Fork            bool    `json:"fork"`
	}

	var allRepos []ghRepo
	truncated := false

	sep := "?"
	if strings.Contains(basePath, "?") {
		sep = "&"
	}

	for page := 1; page <= reposMaxPages; page++ {
		path := fmt.Sprintf("%s%sper_page=%d&page=%d", basePath, sep, reposPageSize, page)
		var batch []ghRepo
		if !c.tryGet(path, &batch) || len(batch) == 0 {
			break
		}
		allRepos = append(allRepos, batch...)
		if len(batch) < reposPageSize {
			break
		}
		if page == reposMaxPages {
			truncated = true
		}
	}

	if excludeForks {
		filtered := allRepos[:0]
		for _, r := range allRepos {
			if !r.Fork {
				filtered = append(filtered, r)
			}
		}
		allRepos = filtered
	}

	langCounts := map[string]int{}
	totalStars, totalForks := 0, 0
	for _, r := range allRepos {
		totalStars += r.StargazersCount
		totalForks += r.ForksCount
		if r.Language != nil && *r.Language != "" {
			langCounts[*r.Language]++
		}
	}

	return &model.CrossRepoSummary{
		RepoCount:            len(allRepos),
		TotalStars:           totalStars,
		TotalForks:           totalForks,
		LanguageDistribution: langCounts,
		ForksExcluded:        excludeForks,
	}, truncated, nil
}

// topN returns the top n entries from counts sorted by value descending.
func topN(counts map[string]int, n int) map[string]int {
	type kv struct {
		k string
		v int
	}
	pairs := make([]kv, 0, len(counts))
	for k, v := range counts {
		pairs = append(pairs, kv{k, v})
	}
	sort.Slice(pairs, func(i, j int) bool { return pairs[i].v > pairs[j].v })
	result := make(map[string]int, n)
	for i, p := range pairs {
		if i >= n {
			break
		}
		result[p.k] = p.v
	}
	return result
}

// orEmpty returns s if non-nil, otherwise an empty slice.
func orEmpty[T any](s []T) []T {
	if s == nil {
		return []T{}
	}
	return s
}
