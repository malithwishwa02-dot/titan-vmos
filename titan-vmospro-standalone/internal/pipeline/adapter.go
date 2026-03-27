package pipeline

import (
	"context"
	"errors"
	"fmt"
)

var ErrEndpointNotImplemented = errors.New("pipeline endpoint not implemented")

type Adapter interface {
	RunContacts(ctx context.Context, padCode string) error
	RunSms(ctx context.Context, padCode string) error
	RunChromeHistory(ctx context.Context, padCode string) error
	RunWallet(ctx context.Context, padCode string) error
}

type OrphanStubAdapter struct{}

func NewOrphanStubAdapter() *OrphanStubAdapter {
	return &OrphanStubAdapter{}
}

func (a *OrphanStubAdapter) RunContacts(ctx context.Context, padCode string) error {
	_ = ctx
	return fmt.Errorf("contacts for %s: %w", padCode, ErrEndpointNotImplemented)
}

func (a *OrphanStubAdapter) RunSms(ctx context.Context, padCode string) error {
	_ = ctx
	return fmt.Errorf("sms for %s: %w", padCode, ErrEndpointNotImplemented)
}

func (a *OrphanStubAdapter) RunChromeHistory(ctx context.Context, padCode string) error {
	_ = ctx
	return fmt.Errorf("chrome history for %s: %w", padCode, ErrEndpointNotImplemented)
}

func (a *OrphanStubAdapter) RunWallet(ctx context.Context, padCode string) error {
	_ = ctx
	return fmt.Errorf("wallet for %s: %w", padCode, ErrEndpointNotImplemented)
}
