#pragma once
// Copy this file to device_config.h (ignored by Git) and replace every placeholder.
// Obtain the private pairing token from your signed-in Cropaganda Device Pairing panel.
// Do NOT use an Auth0 password, Google OAuth secret or API key here.
static const char CROPOGANDA_WIFI_SSID[] = "YOUR_WIFI_SSID";
static const char CROPOGANDA_WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";
static const char CROPOGANDA_DEVICE_ID[] = "esp32-01"; // Must match paired device ID.
static const char CROPOGANDA_DEVICE_TOKEN[] = "YOUR_LONG_PRIVATE_PAIRING_TOKEN";

// Paste the TRUSTED ROOT CA certificate (PEM) for the certificate chain
// of cropaganda.garden. This must be a trusted CA, NOT a copied leaf certificate.
// Verify against the current production chain. Renew it if the CA changes.
// NEVER use tls.setInsecure() to "fix" a certificate failure: this uploader
// transmits an authentication bearer token.
static const char CROPOGANDA_ROOT_CA_PEM[] = R"PEM(
-----BEGIN CERTIFICATE-----
PASTE_THE_PUBLIC_TRUSTED_CA_CERTIFICATE_HERE
-----END CERTIFICATE-----
)PEM";
