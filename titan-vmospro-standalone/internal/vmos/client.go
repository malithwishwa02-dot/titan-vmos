package vmos

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"strings"
)

type Client struct {
	httpClient *http.Client
	baseURL    string
}

func NewClient(httpClient *http.Client, baseURL string) *Client {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	if baseURL == "" {
		baseURL = "https://api.vmoscloud.com"
	}

	return &Client{
		httpClient: httpClient,
		baseURL:    strings.TrimRight(baseURL, "/"),
	}
}

func (c *Client) ListInstances(ctx context.Context, creds Credentials) ([]Instance, error) {
	var out []Instance
	if err := c.do(ctx, creds, http.MethodGet, "/openapi/v1/instances", nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *Client) StartInstance(ctx context.Context, creds Credentials, padCode string) error {
	return c.do(ctx, creds, http.MethodPost, "/openapi/v1/instances/"+padCode+"/start", map[string]string{}, nil)
}

func (c *Client) StopInstance(ctx context.Context, creds Credentials, padCode string) error {
	return c.do(ctx, creds, http.MethodPost, "/openapi/v1/instances/"+padCode+"/stop", map[string]string{}, nil)
}

func (c *Client) ExecShell(ctx context.Context, creds Credentials, padCode string, command string) (*ShellResult, error) {
	req := map[string]string{"command": command}
	var out ShellResult
	if err := c.do(ctx, creds, http.MethodPost, "/openapi/v1/instances/"+padCode+"/shell", req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) do(ctx context.Context, creds Credentials, method, reqPath string, in any, out any) error {
	rawBody := []byte{}
	if in != nil {
		b, err := json.Marshal(in)
		if err != nil {
			return fmt.Errorf("marshal request: %w", err)
		}
		rawBody = b
	}

	nonce, err := newNonce()
	if err != nil {
		return err
	}
	ts := unixNow()
	sig := buildSignature(creds.APISecret, method, reqPath, string(rawBody), ts, nonce)

	fullURL, err := c.resolve(reqPath)
	if err != nil {
		return err
	}

	req, err := http.NewRequestWithContext(ctx, method, fullURL, bytes.NewReader(rawBody))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-KEY", creds.APIKey)
	req.Header.Set("X-API-TIMESTAMP", fmt.Sprintf("%d", ts))
	req.Header.Set("X-API-NONCE", nonce)
	req.Header.Set("X-API-SIGNATURE", sig)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("send request: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var apiErr ErrorResponse
		_ = json.Unmarshal(body, &apiErr)
		if apiErr.Message == "" {
			apiErr.Message = strings.TrimSpace(string(body))
		}
		if apiErr.Message == "" {
			apiErr.Message = "unknown VMOS API error"
		}
		return fmt.Errorf("vmos api status %d: %s", resp.StatusCode, apiErr.Message)
	}

	if out == nil {
		return nil
	}
	if len(body) == 0 {
		return nil
	}
	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	return nil
}

func (c *Client) resolve(reqPath string) (string, error) {
	u, err := url.Parse(c.baseURL)
	if err != nil {
		return "", fmt.Errorf("parse base url: %w", err)
	}
	u.Path = path.Join(u.Path, reqPath)
	return u.String(), nil
}
