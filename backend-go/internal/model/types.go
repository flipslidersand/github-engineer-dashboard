// Package model defines the shared response types for the dashboard API.
// These mirror app/models.py so the Go and Python implementations stay in sync.
package model

type Health struct {
	Status  string `json:"status"`
	Version string `json:"version"`
}

type BenchmarkResult struct {
	URL    string  `json:"url"`
	Type   string  `json:"type"` // "user" | "repo" | "pr" | "issue"
	GoMS   float64 `json:"go_ms"`
}

type RateLimit struct {
	Limit     int `json:"limit"`
	Remaining int `json:"remaining"`
	Used      int `json:"used"`
	Reset     int `json:"reset"` // epoch seconds
}

type RecentFork struct {
	Name     string `json:"name"`
	FullName string `json:"full_name"`
	Stars    int    `json:"stars"`
	UpdatedAt string `json:"updated_at"`
}

type UserActivity struct {
	Username    string         `json:"username"`
	Name        *string        `json:"name"`
	Bio         *string        `json:"bio"`
	Location    *string        `json:"location"`
	Company     *string        `json:"company"`
	Blog        *string        `json:"blog"`
	CreatedAt   *string        `json:"created_at"`
	PublicRepos int            `json:"public_repos"`
	Followers   int            `json:"followers"`
	Following   int            `json:"following"`
	TotalStars  int            `json:"total_stars"`
	EventCounts map[string]int `json:"event_counts"`
	TotalEvents int            `json:"total_events"`
	RepoLanguages map[string]int `json:"repo_languages"`
	RecentForks   []RecentFork   `json:"recent_forks"`
	Cached      bool           `json:"cached"`
}

type Contributor struct {
	Username      string `json:"username"`
	Contributions int    `json:"contributions"`
	AvatarURL     string `json:"avatar_url"`
}

type ChangedFile struct {
	Filename  string `json:"filename"`
	Additions int    `json:"additions"`
	Deletions int    `json:"deletions"`
}

type RepoInfo struct {
	Owner           string        `json:"owner"`
	Name            string        `json:"name"`
	FullName        string        `json:"full_name"`
	Description     *string       `json:"description"`
	Stars           int           `json:"stars"`
	Forks           int           `json:"forks"`
	OpenIssues      int           `json:"open_issues"`
	OpenPRCount     int           `json:"open_pr_count"`
	Language        *string       `json:"language"`
	License         *string       `json:"license"`
	Topics          []string      `json:"topics"`
	UpdatedAt       string        `json:"updated_at"`
	Contributors    []Contributor `json:"contributors"`
	Languages       map[string]int `json:"languages"`
	LatestRelease   *string       `json:"latest_release"`
	LatestReleaseAt *string       `json:"latest_release_at"`
	CommitsLast30d  *int          `json:"commits_last_30d"`
	Cached          bool          `json:"cached"`
}

type PRInfo struct {
	Number            int           `json:"number"`
	Title             string        `json:"title"`
	State             string        `json:"state"` // open | closed | merged
	Author            string        `json:"author"`
	Base              string        `json:"base"`
	Head              string        `json:"head"`
	Additions         int           `json:"additions"`
	Deletions         int           `json:"deletions"`
	ChangedFiles      int           `json:"changed_files"`
	Comments          int           `json:"comments"`
	ReviewComments    int           `json:"review_comments"`
	Reviewers         []string      `json:"reviewers"`
	ReviewWaitHours   *float64      `json:"review_wait_hours"`
	ChangedFilesDetail []ChangedFile `json:"changed_files_detail"`
	CreatedAt         string        `json:"created_at"`
	MergedAt          *string       `json:"merged_at"`
	Cached            bool          `json:"cached"`
}

type IssueInfo struct {
	Number     int      `json:"number"`
	Title      string   `json:"title"`
	State      string   `json:"state"` // open | closed
	Author     string   `json:"author"`
	Labels     []string `json:"labels"`
	Assignees  []string `json:"assignees"`
	Comments   int      `json:"comments"`
	RelatedPRs []int    `json:"related_prs"`
	CreatedAt  string   `json:"created_at"`
	ClosedAt   *string  `json:"closed_at"`
	Cached     bool     `json:"cached"`
}

type ReviewResult struct {
	URL      string `json:"url"`
	PRNumber int    `json:"pr_number"`
	PRTitle  string `json:"pr_title"`
	Markdown string `json:"markdown"`
	Cached   bool   `json:"cached"`
}

type AnalyzeResult struct {
	Type string `json:"type"` // "user" | "repo" | "pr" | "issue"
	URL  string `json:"url"`
	Data any    `json:"data"`
}

type CrossRepoSummary struct {
	Owner                string         `json:"owner"`
	OwnerType            string         `json:"owner_type"` // "user" | "org"
	RepoCount            int            `json:"repo_count"`
	TotalStars           int            `json:"total_stars"`
	TotalForks           int            `json:"total_forks"`
	LanguageDistribution map[string]int `json:"language_distribution"`
	ForksExcluded        bool           `json:"forks_excluded"`
	Truncated            bool           `json:"truncated"`
	Cached               bool           `json:"cached"`
}
