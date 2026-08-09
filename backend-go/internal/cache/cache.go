// Package cache provides a SQLite-backed TTL key-value store.
// Mirrors app/cache.py: entries expire after ttl seconds, stored as JSON.
package cache

import (
	"database/sql"
	"encoding/json"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

const defaultTTL = 300 // 5 minutes

// Cache is a thread-safe SQLite-backed TTL store.
type Cache struct {
	db  *sql.DB
	ttl time.Duration
	mu  sync.Mutex
}

// New opens (or creates) a SQLite database at path and returns a ready Cache.
func New(path string, ttlSeconds int) (*Cache, error) {
	if ttlSeconds <= 0 {
		ttlSeconds = defaultTTL
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS cache (
		key        TEXT PRIMARY KEY,
		value      TEXT NOT NULL,
		expires_at REAL NOT NULL
	)`)
	if err != nil {
		db.Close()
		return nil, err
	}
	return &Cache{db: db, ttl: time.Duration(ttlSeconds) * time.Second}, nil
}

// Get returns the cached value unmarshalled into dst, or false if missing/expired.
func (c *Cache) Get(key string, dst any) bool {
	now := float64(time.Now().UnixNano()) / 1e9
	c.mu.Lock()
	defer c.mu.Unlock()

	var value string
	var expiresAt float64
	err := c.db.QueryRow(
		"SELECT value, expires_at FROM cache WHERE key = ?", key,
	).Scan(&value, &expiresAt)
	if err != nil {
		return false
	}
	if expiresAt <= now {
		_, _ = c.db.Exec("DELETE FROM cache WHERE key = ?", key)
		return false
	}
	return json.Unmarshal([]byte(value), dst) == nil
}

// Set stores value (JSON-encoded) with the configured TTL.
func (c *Cache) Set(key string, value any) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return err
	}
	expiresAt := float64(time.Now().Add(c.ttl).UnixNano()) / 1e9

	c.mu.Lock()
	defer c.mu.Unlock()

	_, err = c.db.Exec(
		`INSERT INTO cache (key, value, expires_at) VALUES (?, ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at`,
		key, string(payload), expiresAt,
	)
	return err
}

// Close closes the underlying database.
func (c *Cache) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.db.Close()
}
