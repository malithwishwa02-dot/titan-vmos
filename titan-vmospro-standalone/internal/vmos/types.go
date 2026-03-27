package vmos

import "time"

type Credentials struct {
	APIKey    string    `json:"apiKey"`
	APISecret string    `json:"apiSecret"`
	BaseURL   string    `json:"baseUrl"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type Instance struct {
	PadCode string `json:"padCode"`
	Name    string `json:"name"`
	Status  string `json:"status"`
}

type ShellResult struct {
	ExitCode int    `json:"exitCode"`
	Output   string `json:"output"`
}

type ErrorResponse struct {
	Message string `json:"message"`
}
