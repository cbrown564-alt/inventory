# 27 — Mobile owner-pairing friction log

**Status:** active — real-phone owner pairing is not yet verified and must not be presented as reliable.

**Scope:** The owner flow from a desktop review to a phone: select **Pair phone**, scan the QR code, open the authenticated owner link, then continue the same review with edit access.

## Executive summary

We replaced a long, capability-bearing URL with a QR-first pairing experience. The QR renderer is now verified in a fresh server and in the live desktop app: it produces a real inline SVG QR code that encodes the owner link. The owner URL also returns the expected review page when opened directly from the laptop over the LAN.

That is not the same as proving the phone journey. A real iPhone Safari attempt reached a failure state: **“Safari couldn't open the page because the server stopped responding.”** The Wi-Fi connection is currently classified by Windows as a **Public** network. That makes the local firewall boundary the leading remaining explanation, but it has not been changed or proven. No successful physical-phone owner-pairing run has been completed.

The key lesson is that a QR image, a local `200` response, and a desktop browser check are useful component checks, but none is an end-to-end acceptance test for a phone on the network.

## What happened

| Stage | Observed experience | Evidence and outcome |
| --- | --- | --- |
| Original handoff | The desktop modal showed a long authenticated URL to copy manually. | High effort and error-prone on a phone; replaced with QR-first pairing. |
| First QR build | The pairing modal displayed a broken-image placeholder instead of a QR code. | The page had an owner URL, but its `PAIR_QR_SRC` value was empty. This was a genuine rendering failure. |
| Clean QR check | A fresh review server generated an inline SVG data URL containing QR paths. | Confirmed working locally; a browser capture showed a real, scannable QR code. |
| Restart check | Restarting still appeared to show the failed QR flow. | Multiple old review-server processes were associated with port 8484. This made the active runtime ambiguous and allowed old code to survive a presumed restart. |
| Process cleanup | Old review-server processes were stopped and one fresh server was launched. | The live modal then contained the SVG QR; this resolved the desktop QR-rendering defect. |
| LAN owner URL check | The exact owner URL loaded from the laptop using its LAN address. | It returned the authenticated owner review page with the expected owner API and media routes. |
| Physical phone check | Scanning opened Safari, then Safari reported that the server stopped responding. | Unresolved. This blocks claiming that owner pairing works on a real phone. |

## Confirmed findings

1. **The QR encoder is working in the current code path.** The renderer now emits an inline SVG data URI rather than relying on an external image service. A fresh server and the current desktop modal both produced QR SVG content.

2. **A stale-process failure made the first diagnosis misleading.** More than one historical review-server process was found with commands targeting port 8484. Killing only the most recent process was insufficient; the page could still be served by an older runtime.

3. **The local owner route works from the laptop.** A request to the exact LAN owner URL returned HTTP 200, and a desktop browser opened the full owner review page.

4. **The real-phone journey is still unverified.** The only physical-device attempt failed after scanning. The desktop checks above do not override that result.

## Likely remaining cause, clearly separated from proof

The Wi-Fi connection (`BT-SPATJ3 2`) is classified by Windows as a **Public** network. The review server is configured to listen on all interfaces when sharing is enabled, and the laptop can reach its own LAN URL. The remaining likely boundary is therefore inbound firewall handling for a Public network.

This is an inference, not a confirmed root cause. Other possibilities include the phone being on an isolated guest segment, client isolation on the access point, an IP change, or a server process exiting during the request. We deliberately did not change the Windows network profile or firewall rule while reporting this incident, because that is a system-wide security change and needs explicit approval.

## Friction and reliability issues

| ID | Severity | Issue | User impact | Needed response |
| --- | --- | --- | --- | --- |
| MP-01 | Major | QR area rendered as a broken image. | The primary handoff action looked unfinished and could not be scanned. | Keep QR generation local and add a rendered-QR regression test. |
| MP-02 | Blocker | Several server processes could coexist around the expected port. | A “restart” did not reliably run the code the user expected. | Detect an occupied port, identify the owning process, and provide a clear stop/restart path. |
| MP-03 | Blocker | LAN sharing had no preflight for Windows Public-network restrictions. | The QR can open a page that the phone cannot actually load. | Surface network readiness before asking the user to scan; do not imply success merely because `--share` was supplied. |
| MP-04 | Major | Owner pairing uses a full-access capability URL. | A copied or photographed link can grant edit access. | Keep the clear owner-access warning, do not place the URL in tenant materials, and provide a way to rotate/revoke it. |
| MP-05 | Moderate | Desktop validation can look successful while phone validation fails. | The user must discover a network failure late, after scanning. | Make a physical-device test an explicit release gate and show connection state after the phone opens the link. |

## Product changes recommended before calling this first-class

### 1. Add a pairing readiness check

Before presenting the QR, show a concise readiness result such as “Phone pairing ready” only after the app has verified its own listener, selected LAN address, and a shareable route. If the network is Public or otherwise cannot be assessed, use a warning that explains the likely need for a trusted/private network or a firewall prompt.

The check must never expose the owner capability URL through an unauthenticated health endpoint. It should validate server reachability and configuration, not reveal the secret token.

### 2. Make server lifecycle visible and deterministic

The share startup output should state the listening address, port, process identity, and a single clear command for stopping that instance. If the intended port is already in use, the CLI should fail with the owning process information instead of allowing an ambiguous restart story.

### 3. Make the modal report a real connection state

The QR modal should retain the QR and copy fallback, then change from “Scan this” to a clear state once the phone has opened the authenticated owner page, for example “Phone connected — you can continue on either device.” This makes the handoff observable instead of relying on a guess from the scan.

### 4. Treat the fallback as support, not the main route

“Copy link instead” remains valuable for devices without a camera or when the camera app cannot recognize the code. It should remain visibly secondary to scanning and continue to warn that the link grants full owner access.

### 5. Add owner-link lifecycle controls

Because the link is a bearer capability, a later iteration should support revoking/rotating the owner pairing link and show when it was last used. That reduces the cost of an accidental disclosure.

## Physical-device acceptance gate

Owner pairing is ready only when all of the following are observed on an actual phone, not simulated solely in a desktop browser:

1. Start exactly one shared review server and confirm one process owns the chosen port.
2. Put the phone and laptop on the same trusted Wi-Fi network.
3. Scan the displayed QR within ten seconds and open the result in the phone browser.
4. Confirm that the phone shows the property overview and authenticated owner state.
5. Make a small allowed owner edit on the phone and confirm it persists when viewed on the desktop.
6. Confirm the tenant link still has tenant-only permissions.
7. Restart the server, confirm the saved owner link continues to work as intended, and confirm no duplicate process remains.

Record the phone model/browser version, Wi-Fi name, Windows network category, any firewall prompt, and the observed result. A local HTTP 200 or a desktop browser page is supporting evidence only, not a substitute for this gate.

## Current verdict

The QR rendering defect is resolved and the desktop/LAN route is healthy. The end-to-end phone handoff is **not** complete: the Safari “server stopped responding” outcome remains a launch blocker. The next work should be a controlled physical-device test after explicitly deciding how the trusted-network and firewall path will be handled.
