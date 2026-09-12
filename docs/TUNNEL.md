# Phone access across different networks

Use a temporary ngrok tunnel when venue Wi-Fi isolates devices, or when the phone needs to use mobile data. **Keep the laptop camera and agent at `http://localhost:8765/?view=camera`.** The tunnel serves a paired phone display through a separate gateway; it does not expose the full application.

## Start and pair

Keep Station Steward running normally. Install/configure your own ngrok agent if needed, following [ngrok's setup guide](https://ngrok.com/docs/getting-started/). Its account token stays in your local ngrok configuration and must not be committed.

From a second PowerShell terminal in the repository:

```powershell
.\start-phone-tunnel.ps1
```

1. On the laptop, open **http://localhost:8766/pair**.
2. Scan its private pairing QR with the Android camera. If ngrok shows its welcome screen, choose **Visit Site** once.
3. On the phone, choose **Arduino bench → Show station passport**.
4. Return to the laptop's original camera page, scan that station passport and start the mission within 30 seconds.

The ordinary connection QR in the original camera page still points to the local network. **Use the separate `/pair` page when connecting through ngrok.** The pairing QR grants phone-display access; keep it out of public recordings. The station passport displayed afterward is the code used by the demo.

The launcher uses a gateway bound to `127.0.0.1:8766` and reuses an existing ngrok tunnel for that exact port when available. Otherwise it starts ngrok in a hidden process. Port overrides are `-Port` for the main app and `-GatewayPort` for the phone gateway. The standard UI links assume the normal main port, 8765.

## Switching Wi-Fi

Leave both the main app and tunnel running. Connect the laptop to the lab Wi-Fi and complete its captive-portal sign-in if prompted. The phone can use any working internet connection, including mobile data. Ngrok detects network changes and reconnects; a brief interruption is expected. [Official ngrok FAQ](https://ngrok.com/docs/faq).

The OpenAI key and encrypted Ambiguous connection remain on the laptop. Switching Wi-Fi does not change their configuration, although outgoing API requests still need working internet. A tunnel does not bypass venue sign-in or network blocking.

Refresh the phone after internet returns. If the gateway was restarted, scan a new pairing QR because restart rotates its access token. Pairing lasts at most four hours. If a station passport expires, select **Show station passport** again and rescan it on the laptop.

## Access boundaries

- A random pairing link establishes an HTTPS-only, HttpOnly cookie. The public landing URL then drops the token.
- The gateway permits station selection, sanitized passport state, passport QR images and public frontend assets. Raw decoder results are removed from returned passport JSON.
- Agent, hardware, Ambiguous, camera-upload and replay APIs are denied through the gateway, even to a paired phone.
- Public requests must use the current tunnel hostname. Passport creation additionally requires the matching HTTPS origin, JSON and a small request body; creation is limited to once every two seconds.
- The pairing page is available only through the laptop's localhost address. Forwarded requests cannot obtain it.
- The gateway does not read provider credentials. It uses a fixed localhost upstream and does not forward the caller's cookies, authorization or forwarding headers.

Local ngrok request inspection and gateway access logs are disabled. This does not promise zero ngrok service logging: ngrok terminates HTTPS and its cloud metadata/capture settings are separate. [Traffic inspection documentation](https://ngrok.com/docs/obs/traffic-inspection).

Stop the gateway terminal with **Ctrl+C** after the demo. The launcher also stops ngrok if it started that process. A reused ngrok process remains owned by its original terminal; stop it there when finished. Once the gateway stops, its phone endpoints are unavailable.

## Verification

The gateway has 11 offline checks covering pairing, origin/host checks, body limits, passport sanitization and denial of private APIs. A live HTTP check through the ngrok endpoint confirmed the paired phone page, a frontend script and station state, while unpaired requests and private routes were denied. A paired HTTPS request also created an Arduino passport and loaded its QR; the laptop reported the same still-unscanned passport. No mission or human task was created by this check. The combined offline suite passed all 128 tests. These are HTTP and offline checks; an Android trial after switching to the lab Wi-Fi remains a device/network check.
