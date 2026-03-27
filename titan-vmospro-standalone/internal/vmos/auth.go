package vmos

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strconv"
	"time"
)

func buildSignature(secret, method, path, body string, ts int64, nonce string) string {
	payload := method + "\n" + path + "\n" + body + "\n" + strconv.FormatInt(ts, 10) + "\n" + nonce
	h := hmac.New(sha256.New, []byte(secret))
	_, _ = h.Write([]byte(payload))
	return hex.EncodeToString(h.Sum(nil))
}

func newNonce() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("create nonce: %w", err)
	}
	return hex.EncodeToString(b), nil
}

func unixNow() int64 {
	return time.Now().Unix()
}
