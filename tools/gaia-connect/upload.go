package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type importRequest struct {
	Token   string   `json:"token"`
	Cookies []Cookie `json:"cookies"`
	Origins []any    `json:"origins"`
}

type importedHost struct {
	Domain string `json:"domain"`
}

type importResponse struct {
	Imported    []importedHost `json:"imported"`
	HostCount   int            `json:"host_count"`
	CookieCount int            `json:"cookie_count"`
}

// MintToken asks a localhost dev API for a single-use import code (dev-bypass
// auth). Prod callers pass their own --token from the web app instead.
func MintToken(apiBase string) (string, error) {
	resp, err := http.Post(apiBase+"/api/v1/browser/import/token", "application/json", nil)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("mint failed (%d): %s", resp.StatusCode, body)
	}
	var out struct {
		Token string `json:"token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	return out.Token, nil
}

// Upload posts the selected cookies to GAIA's import endpoint.
func Upload(apiBase, token string, cookies []Cookie) (importResponse, error) {
	body, err := json.Marshal(importRequest{Token: token, Cookies: cookies, Origins: []any{}})
	if err != nil {
		return importResponse{}, err
	}
	client := &http.Client{Timeout: 30 * time.Second}
	req, err := http.NewRequest(http.MethodPost, apiBase+"/api/v1/browser/import", bytes.NewReader(body))
	if err != nil {
		return importResponse{}, err
	}
	req.Header.Set("content-type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return importResponse{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return importResponse{}, fmt.Errorf("upload rejected (%d): %s", resp.StatusCode, b)
	}
	var out importResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return importResponse{}, err
	}
	return out, nil
}
