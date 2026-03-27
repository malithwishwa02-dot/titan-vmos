package vmos

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

type CredentialStore struct {
	path string
}

func NewCredentialStore() *CredentialStore {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	return &CredentialStore{
		path: filepath.Join(home, ".config", "titan-vmospro-standalone", "credentials.enc"),
	}
}

func (s *CredentialStore) Save(creds Credentials) error {
	creds.UpdatedAt = time.Now().UTC()
	raw, err := json.Marshal(creds)
	if err != nil {
		return fmt.Errorf("marshal credentials: %w", err)
	}
	enc, err := s.encrypt(raw)
	if err != nil {
		return err
	}

	if err := os.MkdirAll(filepath.Dir(s.path), 0o700); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}
	if err := os.WriteFile(s.path, enc, 0o600); err != nil {
		return fmt.Errorf("write credentials: %w", err)
	}
	return nil
}

func (s *CredentialStore) Load() (Credentials, error) {
	raw, err := os.ReadFile(s.path)
	if err != nil {
		return Credentials{}, fmt.Errorf("read credentials: %w", err)
	}
	plain, err := s.decrypt(raw)
	if err != nil {
		return Credentials{}, err
	}

	var creds Credentials
	if err := json.Unmarshal(plain, &creds); err != nil {
		return Credentials{}, fmt.Errorf("unmarshal credentials: %w", err)
	}
	return creds, nil
}

func (s *CredentialStore) encrypt(plain []byte) ([]byte, error) {
	block, err := aes.NewCipher(masterKey())
	if err != nil {
		return nil, fmt.Errorf("init cipher: %w", err)
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("init gcm: %w", err)
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, fmt.Errorf("nonce: %w", err)
	}
	sealed := gcm.Seal(nonce, nonce, plain, nil)
	return sealed, nil
}

func (s *CredentialStore) decrypt(raw []byte) ([]byte, error) {
	block, err := aes.NewCipher(masterKey())
	if err != nil {
		return nil, fmt.Errorf("init cipher: %w", err)
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("init gcm: %w", err)
	}
	if len(raw) < gcm.NonceSize() {
		return nil, errors.New("ciphertext too short")
	}
	nonce, data := raw[:gcm.NonceSize()], raw[gcm.NonceSize():]
	plain, err := gcm.Open(nil, nonce, data, nil)
	if err != nil {
		return nil, fmt.Errorf("decrypt credentials: %w", err)
	}
	return plain, nil
}

func masterKey() []byte {
	seed := os.Getenv("TITAN_VMOS_MASTER_KEY")
	if seed == "" {
		host, _ := os.Hostname()
		seed = "titan-vmospro-standalone:" + host
	}
	sum := sha256.Sum256([]byte(seed))
	return sum[:]
}
