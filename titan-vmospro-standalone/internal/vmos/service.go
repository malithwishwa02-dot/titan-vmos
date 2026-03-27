package vmos

import (
	"context"
	"errors"
	"fmt"
)

type TitanService struct {
	client *Client
	store  *CredentialStore
}

func NewTitanService(client *Client, store *CredentialStore) *TitanService {
	return &TitanService{client: client, store: store}
}

func (s *TitanService) Configure(ctx context.Context, creds Credentials) error {
	_ = ctx
	if creds.APIKey == "" || creds.APISecret == "" {
		return errors.New("api key and secret are required")
	}
	if creds.BaseURL == "" {
		creds.BaseURL = "https://api.vmoscloud.com"
	}
	return s.store.Save(creds)
}

func (s *TitanService) ListDevices(ctx context.Context) ([]Instance, error) {
	creds, err := s.store.Load()
	if err != nil {
		return nil, fmt.Errorf("load credentials: %w", err)
	}
	return s.client.ListInstances(ctx, creds)
}

func (s *TitanService) StartDevice(ctx context.Context, padCode string) error {
	creds, err := s.store.Load()
	if err != nil {
		return fmt.Errorf("load credentials: %w", err)
	}
	return s.client.StartInstance(ctx, creds, padCode)
}

func (s *TitanService) StopDevice(ctx context.Context, padCode string) error {
	creds, err := s.store.Load()
	if err != nil {
		return fmt.Errorf("load credentials: %w", err)
	}
	return s.client.StopInstance(ctx, creds, padCode)
}

func (s *TitanService) ConnectSession(ctx context.Context, padCode string) (*ShellResult, error) {
	creds, err := s.store.Load()
	if err != nil {
		return nil, fmt.Errorf("load credentials: %w", err)
	}
	return s.client.ExecShell(ctx, creds, padCode, "echo titan_session_ready")
}
