package genesis

import (
	"context"
	"errors"
	"testing"

	"github.com/titan-v13-device/titan-vmospro-standalone/internal/pipeline"
	"github.com/titan-v13-device/titan-vmospro-standalone/internal/vmos"
)

type fakeTitan struct {
	err error
}

func (f *fakeTitan) ConnectSession(ctx context.Context, padCode string) (*vmos.ShellResult, error) {
	_ = ctx
	_ = padCode
	if f.err != nil {
		return nil, f.err
	}
	return &vmos.ShellResult{ExitCode: 0, Output: "ok"}, nil
}

func TestRunWithStubbedSteps(t *testing.T) {
	orch := NewOrchestrator(&fakeTitan{}, pipeline.NewOrphanStubAdapter())

	out, err := orch.Run(context.Background(), RunRequest{
		PadCode: "PAD-1",
		Steps:   []string{"contacts", "sms"},
	})
	if err != nil {
		t.Fatalf("run failed: %v", err)
	}
	if out.Steps["contacts"].(map[string]any)["status"] != "stubbed" {
		t.Fatalf("expected contacts to be stubbed: %+v", out.Steps)
	}
}

func TestRunPropagatesSessionError(t *testing.T) {
	orch := NewOrchestrator(&fakeTitan{err: errors.New("connect fail")}, pipeline.NewOrphanStubAdapter())
	_, err := orch.Run(context.Background(), RunRequest{
		PadCode: "PAD-1",
		Steps:   []string{"contacts"},
	})
	if err == nil {
		t.Fatalf("expected error")
	}
}
