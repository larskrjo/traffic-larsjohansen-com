/**
 * Native Sign in with Apple button.
 *
 * Wraps `expo-apple-authentication`, which is Apple's first-party
 * `AuthenticationServices.framework` exposed to React Native. The
 * button itself (`AppleAuthenticationButton`) is a real
 * `ASAuthorizationAppleIDButton` rendered by UIKit — Apple's HIG
 * requires that exact button (you can't legally substitute a
 * custom-styled "Continue with Apple" button on iOS), and on
 * iOS 26+ it picks up the system Liquid Glass treatment automatically
 * because AuthenticationServices participates in the new chrome.
 *
 * Successful sign-in posts the `identityToken` (Apple-signed JWT)
 * plus the optional first-run display name to
 * `POST /api/v1/auth/apple`. The backend verifies the JWT against
 * Apple's published JWKs (no client secret needed) and issues a
 * session token, identical to the Google path.
 *
 * iOS-only: this component returns `null` on Android. Android users
 * sign in with Google.
 */
import { useState } from "react";
import { Platform, View, type StyleProp, type ViewStyle } from "react-native";
import * as AppleAuthentication from "expo-apple-authentication";
import { useTheme } from "react-native-paper";

import { isApiError } from "@time2leave/shared";

import { useAuth } from "~/auth/AuthProvider";

type Props = {
    /** Outer container style — typically `{ borderRadius, shadow… }`. */
    style?: StyleProp<ViewStyle>;
    /**
     * Pixel height of the native button. Apple's HIG mandates a
     * minimum of 32pt; we match the 52pt CTA pill height used for
     * the Google button so the two read as a balanced pair on the
     * splash.
     */
    height?: number;
    /**
     * Fired the moment the user taps the button (before the Apple
     * sheet is presented). The splash uses this to clear any
     * lingering allowlist-rejection banner so a retry shows fresh
     * feedback instead of a stale message from the previous attempt.
     */
    onAttemptStart?: () => void;
    /**
     * Fired only when the backend returns 403 from `/auth/apple` —
     * i.e. Apple authenticated the user but the email isn't on the
     * invite allowlist. The splash converts this into a "you're
     * not on the invite list" banner.
     */
    onAllowlistRejected?: () => void;
    /**
     * Fired for every *non-cancel* failure that isn't a 403:
     *   - the backend returned 401 (invalid token) or 5xx (transient
     *     server/DB error — historically e.g. the `apple_sub`
     *     schema-drift bug that 500-ed every TestFlight sign-in),
     *   - the network request itself failed (airplane mode, captive
     *     portal, AWS hiccup),
     *   - Apple's framework returned a non-cancel error
     *     (`ERR_REQUEST_FAILED`, `ERR_REQUEST_UNKNOWN`, etc.),
     *   - or Apple completed but handed us no `identityToken` (App
     *     ID misconfiguration).
     * The splash converts this into a generic "couldn't sign in,
     * try again" banner. User cancels (`ERR_REQUEST_CANCELED`) are
     * still dismissed silently — same UX as the system sheet.
     */
    onUnexpectedError?: () => void;
};

export function AppleSignInButton({
    style,
    height = 52,
    onAttemptStart,
    onAllowlistRejected,
    onUnexpectedError,
}: Props) {
    const theme = useTheme();
    const { signInWithApple } = useAuth();
    const [busy, setBusy] = useState(false);

    if (Platform.OS !== "ios") return null;

    const handlePress = async () => {
        if (busy) return;
        onAttemptStart?.();
        setBusy(true);
        try {
            const credential = await AppleAuthentication.signInAsync({
                // FULL_NAME and EMAIL are only delivered on the
                // *first* authorization for this app + Apple ID
                // pair. Subsequent sign-ins return `null` for
                // both — that's by design (Apple's privacy
                // pitch). The backend handles both cases via
                // `apple_sub`-based re-identification.
                requestedScopes: [
                    AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
                    AppleAuthentication.AppleAuthenticationScope.EMAIL,
                ],
            });

            if (!credential.identityToken) {
                // Apple completed the sheet but returned no token —
                // a configuration bug (Sign-in-with-Apple capability
                // missing from the App ID, primary App ID not set,
                // etc.). Treat as an unexpected failure so the
                // splash banner tells the user *something* went
                // wrong instead of silently dismissing.
                console.warn(
                    "AppleSignInButton: no identity token returned — check 'Sign in with Apple' is enabled on the App ID at developer.apple.com.",
                );
                onUnexpectedError?.();
                return;
            }

            // Apple gives us the user's name as a structured object
            // *only* on first sign-in. Flatten to a single string the
            // backend can store as the display name. Trim and
            // collapse whitespace so an absent middle name doesn't
            // produce "Lars  Johansen".
            const fullName = credential.fullName
                ? [
                      credential.fullName.givenName,
                      credential.fullName.middleName,
                      credential.fullName.familyName,
                  ]
                      .filter(Boolean)
                      .join(" ")
                      .trim()
                : null;

            await signInWithApple(
                credential.identityToken,
                fullName && fullName.length > 0 ? fullName : null,
            );
        } catch (err: unknown) {
            // Three buckets, in order of specificity:
            //   1. user cancelled the Apple sheet -> silent (no
            //      banner, no log noise; the user explicitly opted
            //      out of signing in),
            //   2. backend allowlist rejection (HTTP 403) -> "you're
            //      not on the invite list" banner,
            //   3. anything else (network error, 401 invalid token,
            //      5xx server error, ERR_REQUEST_FAILED / UNKNOWN
            //      from Apple's framework) -> generic "couldn't
            //      sign in, try again" banner. Silently dropping
            //      these was the bug that masked the prod
            //      `apple_sub` schema-drift outage for hours.
            if (isAppleCancelError(err)) {
                // Silent on cancel — same UX as the system sheet.
            } else if (isApiError(err) && err.status === 403) {
                onAllowlistRejected?.();
            } else {
                onUnexpectedError?.();
            }
            console.warn("AppleSignInButton: sign-in failed", err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <View
            style={[
                {
                    borderRadius: 28,
                    overflow: "hidden",
                    opacity: busy ? 0.6 : 1,
                    shadowColor: "#000",
                    shadowOpacity: theme.dark ? 0.4 : 0.12,
                    shadowRadius: 12,
                    shadowOffset: { width: 0, height: 4 },
                    elevation: 4,
                },
                style,
            ]}
        >
            <AppleAuthentication.AppleAuthenticationButton
                buttonType={
                    AppleAuthentication.AppleAuthenticationButtonType
                        .CONTINUE
                }
                buttonStyle={
                    theme.dark
                        ? AppleAuthentication
                              .AppleAuthenticationButtonStyle.WHITE
                        : AppleAuthentication
                              .AppleAuthenticationButtonStyle.BLACK
                }
                cornerRadius={28}
                style={{ width: "100%", height }}
                onPress={() => {
                    void handlePress();
                }}
            />
        </View>
    );
}

/**
 * AuthenticationServices.framework reports user cancellation by
 * throwing an error whose `code` is the string `"ERR_REQUEST_CANCELED"`
 * (documented at
 * https://docs.expo.dev/versions/latest/sdk/apple-authentication/#error-codes).
 * Distinguish it cleanly from "real" failures so cancels stay silent
 * while everything else (`ERR_REQUEST_FAILED`, `ERR_REQUEST_UNKNOWN`,
 * etc.) surfaces as a "try again" banner.
 */
function isAppleCancelError(err: unknown): boolean {
    return (
        typeof err === "object" &&
        err !== null &&
        "code" in err &&
        (err as { code?: unknown }).code === "ERR_REQUEST_CANCELED"
    );
}
