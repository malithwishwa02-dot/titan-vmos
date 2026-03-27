package main

import (
	"context"
	"embed"
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed frontend/dist/*
var assets embed.FS

func main() {
	ctx := context.Background()
	app := NewApp()

	if _, err := app.Health(ctx); err != nil {
		log.Fatalf("startup health check failed: %v", err)
	}

	if err := wails.Run(&options.App{
		Title:  "Titan VMOS Pro Standalone",
		Width:  1200,
		Height: 760,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		Bind: []interface{}{
			app,
		},
	}); err != nil {
		log.Fatalf("failed to start desktop app: %v", err)
	}
}
