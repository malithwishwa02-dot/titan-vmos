package vmos

import "testing"

func TestBuildSignatureDeterministic(t *testing.T) {
	got := buildSignature("secret", "POST", "/openapi/v1/instances", `{"a":"b"}`, 1700000000, "abc")
	want := "3d429665bf8cb7e4653f644db8a699aa43ccc9b9cc78893267dbfaac54528004"
	if got != want {
		t.Fatalf("signature mismatch: got %s want %s", got, want)
	}
}
