package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/titan-v13-device/titan-vmospro-standalone/internal/genesis"
	"github.com/titan-v13-device/titan-vmospro-standalone/internal/pipeline"
	"github.com/titan-v13-device/titan-vmospro-standalone/internal/vmos"
)

type App struct {
	service *vmos.TitanService
	genesis *genesis.Orchestrator
}

func NewApp() *App {
	store := vmos.NewCredentialStore()
	client := vmos.NewClient(http.DefaultClient, "https://api.vmoscloud.com")
	service := vmos.NewTitanService(client, store)
	pipe := pipeline.NewOrphanStubAdapter()
	orch := genesis.NewOrchestrator(service, pipe)

	return &App{
		service: service,
		genesis: orch,
	}
}

func (a *App) Health(ctx context.Context) (string, error) {
	if a.service == nil || a.genesis == nil {
		return "", errors.New("app dependencies are not initialized")
	}

	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	_ = ctx
	return "ok", nil
}

func (a *App) GetStatus() (map[string]string, error) {
	health, err := a.Health(context.Background())
	if err != nil {
		return nil, err
	}
	return map[string]string{
		"health": health,
		"name":   "Titan VMOS Pro Standalone",
	}, nil
}

func (a *App) Ping(name string) string {
	if name == "" {
		name = "operator"
	}
	return fmt.Sprintf("hello %s, app is running", name)
}
