package vmos

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestClientListInstancesMock(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/openapi/v1/instances" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		if r.Header.Get("X-API-KEY") != "key" {
			t.Fatalf("missing auth key")
		}
		if r.Header.Get("X-API-SIGNATURE") == "" {
			t.Fatalf("missing signature")
		}
		_ = json.NewEncoder(w).Encode([]Instance{
			{PadCode: "PAD1", Name: "Device1", Status: "running"},
		})
	}))
	defer srv.Close()

	client := NewClient(srv.Client(), srv.URL)
	out, err := client.ListInstances(context.Background(), Credentials{
		APIKey:    "key",
		APISecret: "secret",
		BaseURL:   srv.URL,
	})
	if err != nil {
		t.Fatalf("ListInstances failed: %v", err)
	}
	if len(out) != 1 || out[0].PadCode != "PAD1" {
		t.Fatalf("unexpected response: %+v", out)
	}
}

func TestClientErrorResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"message":"invalid request"}`))
	}))
	defer srv.Close()

	client := NewClient(srv.Client(), srv.URL)
	_, err := client.ListInstances(context.Background(), Credentials{
		APIKey:    "key",
		APISecret: "secret",
	})
	if err == nil || !strings.Contains(err.Error(), "invalid request") {
		t.Fatalf("expected decoded API error, got %v", err)
	}
}
