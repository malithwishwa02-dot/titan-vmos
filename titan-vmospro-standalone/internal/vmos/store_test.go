package vmos

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCredentialStoreRoundTrip(t *testing.T) {
	t.Setenv("TITAN_VMOS_MASTER_KEY", "unit-test-key")
	tmp := t.TempDir()
	store := &CredentialStore{path: filepath.Join(tmp, "credentials.enc")}

	in := Credentials{
		APIKey:    "key",
		APISecret: "secret",
		BaseURL:   "https://api.example.test",
	}
	if err := store.Save(in); err != nil {
		t.Fatalf("save failed: %v", err)
	}

	stat, err := os.Stat(store.path)
	if err != nil {
		t.Fatalf("stat failed: %v", err)
	}
	if stat.Mode().Perm() != 0o600 {
		t.Fatalf("expected 0600 permissions, got %o", stat.Mode().Perm())
	}

	out, err := store.Load()
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}

	if out.APIKey != in.APIKey || out.APISecret != in.APISecret || out.BaseURL != in.BaseURL {
		t.Fatalf("credentials mismatch: got %+v", out)
	}
	if out.UpdatedAt.IsZero() {
		t.Fatalf("expected updated timestamp")
	}
}
