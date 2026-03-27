package genesis

import (
	"context"
	"errors"
	"fmt"

	"github.com/titan-v13-device/titan-vmospro-standalone/internal/pipeline"
	"github.com/titan-v13-device/titan-vmospro-standalone/internal/vmos"
)

type titanAPI interface {
	ConnectSession(ctx context.Context, padCode string) (*vmos.ShellResult, error)
}

type Orchestrator struct {
	titan    titanAPI
	pipeline pipeline.Adapter
}

func NewOrchestrator(titan titanAPI, adapter pipeline.Adapter) *Orchestrator {
	return &Orchestrator{
		titan:    titan,
		pipeline: adapter,
	}
}

type RunRequest struct {
	PadCode string   `json:"padCode"`
	Steps   []string `json:"steps"`
}

type RunResult struct {
	PadCode string         `json:"padCode"`
	Steps   map[string]any `json:"steps"`
}

func (o *Orchestrator) Run(ctx context.Context, req RunRequest) (*RunResult, error) {
	if req.PadCode == "" {
		return nil, errors.New("padCode is required")
	}
	if len(req.Steps) == 0 {
		return nil, errors.New("at least one step is required")
	}

	if _, err := o.titan.ConnectSession(ctx, req.PadCode); err != nil {
		return nil, fmt.Errorf("connect session: %w", err)
	}

	out := &RunResult{
		PadCode: req.PadCode,
		Steps:   map[string]any{},
	}

	for _, step := range req.Steps {
		err := o.runStep(ctx, req.PadCode, step)
		if err == nil {
			out.Steps[step] = map[string]any{"status": "ok"}
			continue
		}
		if errors.Is(err, pipeline.ErrEndpointNotImplemented) {
			out.Steps[step] = map[string]any{"status": "stubbed", "error": err.Error()}
			continue
		}
		out.Steps[step] = map[string]any{"status": "failed", "error": err.Error()}
		return out, err
	}
	return out, nil
}

func (o *Orchestrator) runStep(ctx context.Context, padCode, step string) error {
	switch step {
	case "contacts":
		return o.pipeline.RunContacts(ctx, padCode)
	case "sms":
		return o.pipeline.RunSms(ctx, padCode)
	case "chrome_history":
		return o.pipeline.RunChromeHistory(ctx, padCode)
	case "wallet":
		return o.pipeline.RunWallet(ctx, padCode)
	default:
		return fmt.Errorf("unknown step %q", step)
	}
}
