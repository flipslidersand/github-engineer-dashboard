package main

import (
	"log"
	"net/http"
	"os"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/flipslidersand/github-engineer-dashboard/backend-go/internal/cache"
	"github.com/flipslidersand/github-engineer-dashboard/backend-go/internal/handler"
)

func main() {
	port := getenv("PORT", "8080")
	cacheDB := getenv("CACHE_DB", "cache-go.db")
	ttl := 300

	c, err := cache.New(cacheDB, ttl)
	if err != nil {
		log.Fatalf("cache init: %v", err)
	}
	defer c.Close()

	deps := &handler.Deps{
		Cache:        c,
		GithubToken:  os.Getenv("GITHUB_TOKEN"),
		GithubAPIURL: getenv("GITHUB_API_URL", "https://api.github.com"),
	}

	r := chi.NewRouter()
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	handler.Register(r, deps)

	log.Printf("github-engineer-dashboard go backend listening on :%s", port)
	if err := http.ListenAndServe(":"+port, r); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
