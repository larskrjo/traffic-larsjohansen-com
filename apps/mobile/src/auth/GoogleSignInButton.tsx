/**
 * Native Google Sign-In button.
 *
 * Wraps `@react-native-google-signin/google-signin` so the user gets
 * Apple's "Continue with Google" sheet on iOS and the Google account
 * picker on Android. The returned `idToken` is posted to
 * `POST /api/v1/auth/google` (with `X-Client: mobile` so the backend
 * echoes a session JWT we persist in `expo-secure-store`).
 *
 * This component is only rendered when the env validator confirms
 * `appEnv === "prod"` and both OAuth client IDs are present; it does
 * not need to handle the "not configured" case.
 *
 * Visuals follow Google's branding guidelines for sign-in buttons:
 *   - Light mode: white pill, dark text, multicolour "G" mark.
 *   - Dark mode:  ~black pill (#1f1f1f), white text, white "G" mark.
 *   - Both modes get a subtle hairline border so the pill is visible
 *     against any background.
 *   - Tap target is the same 52 px-tall iOS-pill we use elsewhere.
 *
 * We render it as a plain Pressable + View rather than a Paper Button
 * because Paper's `mode="contained"` paints the pill with the theme
 * primary, which ends up lavender on dark mode — off-spec for Google
 * sign-in and an obvious "weird color combo" on the splash.
 */
import { useEffect, useState } from "react";
import {
    ActivityIndicator,
    Platform,
    Pressable,
    StyleSheet,
    Text,
    View,
    type StyleProp,
    type TextStyle,
    type ViewStyle,
} from "react-native";
import { Icon, useTheme } from "react-native-paper";
import {
    GoogleSignin,
    statusCodes,
} from "@react-native-google-signin/google-signin";

import { isApiError } from "@time2leave/shared";

import { useAuth } from "~/auth/AuthProvider";
import { requireEnv } from "~/config/env";

type Props = {
    /** Outer style (e.g. `borderRadius` overrides). */
    style?: StyleProp<ViewStyle>;
    /** Inner content style — use to grow the tap target. */
    contentStyle?: StyleProp<ViewStyle>;
    /** Label style — use to upweight the label or change its size. */
    labelStyle?: StyleProp<TextStyle>;
    /**
     * Fired the moment the user taps the button (before Google's
     * sheet appears). The splash uses this to clear any lingering
     * allowlist-rejection banner so a retry shows fresh feedback.
     */
    onAttemptStart?: () => void;
    /**
     * Fired only when the backend returns 403 from `/auth/google` —
     * i.e. Google authenticated the user but the email isn't on
     * the invite allowlist. The splash converts this into a "you're
     * not on the invite list" banner.
     */
    onAllowlistRejected?: () => void;
    /**
     * Fired for every *non-cancel* failure that isn't a 403:
     *   - the backend returned 401 (invalid token) or 5xx (transient
     *     server/DB error — historically e.g. the `apple_sub`
     *     schema-drift bug that 500-ed every TestFlight sign-in),
     *   - the network request itself failed,
     *   - Google Play services are missing / out-of-date,
     *   - or Google completed but handed us no `idToken`.
     * The splash converts this into a generic "couldn't sign in,
     * try again" banner. User cancels (`SIGN_IN_CANCELLED`) are
     * still dismissed silently — same UX as Google's own apps.
     */
    onUnexpectedError?: () => void;
};

let configured = false;

function ensureConfigured(): void {
    if (configured) return;
    const env = requireEnv();
    if (env.appEnv !== "prod") {
        // The splash never renders this button outside prod mode; if
        // we got here, something is very wrong.
        throw new Error(
            "<GoogleSignInButton> mounted with EXPO_PUBLIC_APP_ENV=local. Check the splash routing.",
        );
    }
    GoogleSignin.configure({
        // The web client ID becomes the `aud` claim of the ID token
        // Google hands back to us — backend's `verify_google_id_token`
        // matches it against the comma-separated `GOOGLE_OAUTH_CLIENT_ID`
        // list, which must include both web + iOS + Android client IDs.
        webClientId: env.googleOAuthWebClientId,
        iosClientId: env.googleOAuthIosClientId,
        scopes: ["profile", "email"],
        offlineAccess: false,
    });
    configured = true;
}

export function GoogleSignInButton({
    style,
    contentStyle,
    labelStyle,
    onAttemptStart,
    onAllowlistRejected,
    onUnexpectedError,
}: Props = {}) {
    const theme = useTheme();
    const isDark = theme.dark;
    const { signInWithGoogle } = useAuth();
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        ensureConfigured();
    }, []);

    // Google brand-spec colours per
    // https://developers.google.com/identity/branding-guidelines.
    const pillBg = isDark ? "#1f1f1f" : "#ffffff";
    const pillTextColor = isDark ? "#e3e3e3" : "#1f1f1f";
    const pillBorder = isDark
        ? "rgba(255,255,255,0.16)"
        : "rgba(0,0,0,0.10)";

    const handlePress = async () => {
        onAttemptStart?.();
        setBusy(true);
        try {
            await GoogleSignin.hasPlayServices({
                showPlayServicesUpdateDialog: true,
            });
            const result = await GoogleSignin.signIn();
            // The shape changed in v13 — `data` carries the user
            // payload + idToken on success; older versions returned
            // it at the top level. Handle both for safety.
            const idToken =
                (result as { data?: { idToken?: string | null } }).data
                    ?.idToken ??
                (result as { idToken?: string | null }).idToken ??
                null;
            if (!idToken) {
                // Google's sheet closed without giving us a token —
                // a configuration bug (wrong webClientId, missing
                // SHA-1 fingerprint on Android, etc.) rather than a
                // user choice. Treat as an unexpected failure so
                // the splash surfaces a "try again" banner.
                console.warn(
                    "GoogleSignInButton: no ID token returned — check OAuth client configuration for this platform.",
                );
                onUnexpectedError?.();
                return;
            }
            await signInWithGoogle(idToken);
        } catch (err: unknown) {
            // Three buckets, in order of specificity:
            //   1. user cancelled the Google sheet -> silent (no
            //      banner, no log noise; the user explicitly opted
            //      out of signing in),
            //   2. backend allowlist rejection (HTTP 403) -> "you're
            //      not on the invite list" banner,
            //   3. anything else (network error, 401 invalid token,
            //      5xx server error, missing Play services) ->
            //      generic "couldn't sign in, try again" banner.
            //      Silently dropping these was the bug that masked
            //      the prod `apple_sub` schema-drift outage that
            //      500-ed every TestFlight sign-in for hours.
            if (isGoogleCancelError(err)) {
                // Silent on cancel — same UX as Google's own apps.
            } else if (isApiError(err) && err.status === 403) {
                onAllowlistRejected?.();
            } else {
                onUnexpectedError?.();
            }
            console.warn("GoogleSignInButton: sign-in failed", err);
        } finally {
            setBusy(false);
        }
    };

    return (
        // `width: "100%"` on both the outer View and the Pressable
        // is deliberate: Apple's `AppleAuthenticationButton` is
        // rendered with an explicit `width: "100%"` (see
        // `AppleSignInButton`), so without matching widths here the
        // Google pill collapses to fit its content and reads
        // narrower than the Apple button on the splash. Pressables
        // do not auto-stretch in flex parents the way bare Views do
        // in every RN version, so we set the width explicitly.
        <View style={{ width: "100%" }}>
            <Pressable
                onPress={busy ? undefined : handlePress}
                accessibilityRole="button"
                accessibilityLabel="Continue with Google"
                accessibilityState={{ disabled: busy }}
                style={({ pressed }) => [
                    {
                        width: "100%",
                        borderRadius: 28,
                        overflow: "hidden",
                        opacity: busy ? 0.6 : pressed ? 0.85 : 1,
                        shadowColor: "#000",
                        shadowOpacity: isDark ? 0.4 : 0.12,
                        shadowRadius: 12,
                        shadowOffset: { width: 0, height: 4 },
                        elevation: 4,
                    },
                    style,
                ]}
            >
                <View
                    style={[
                        {
                            flexDirection: "row",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: 12,
                            minHeight: 52,
                            paddingHorizontal: 24,
                            backgroundColor: pillBg,
                            borderWidth: StyleSheet.hairlineWidth,
                            borderColor: pillBorder,
                            borderRadius: 28,
                        },
                        contentStyle,
                    ]}
                >
                    {busy ? (
                        <ActivityIndicator size="small" color={pillTextColor} />
                    ) : (
                        <Icon source="google" size={18} color={pillTextColor} />
                    )}
                    <Text
                        // Use the platform's native `Text` (not
                        // Paper's) so the label inherits the iOS
                        // system font (SF Pro) directly. Apple's
                        // `ASAuthorizationAppleIDButton` auto-scales
                        // its "Continue with Apple" label as a
                        // function of the button's `cornerRadius`
                        // (≈`cornerRadius * 0.7`) in SF Pro *medium*
                        // — at our 28pt corner radius that's
                        // roughly 19pt. We size this label to match
                        // so the two CTAs read as a balanced pair on
                        // the splash. Paper's `Text` would otherwise
                        // inject MD3 typography (`bodyLarge` ships
                        // with `letterSpacing: 0.5`), and `"600"`
                        // (semibold) reads visibly heavier than
                        // Apple's button — both make the two CTAs
                        // look mismatched.
                        style={[
                            {
                                color: pillTextColor,
                                fontFamily: Platform.select({
                                    ios: "System",
                                    android: "sans-serif-medium",
                                }),
                                fontSize: 20,
                                fontWeight: "500",
                                letterSpacing: 0,
                            },
                            labelStyle,
                        ]}
                    >
                        Continue with Google
                    </Text>
                </View>
            </Pressable>
        </View>
    );
}

/**
 * `@react-native-google-signin/google-signin` surfaces user cancellation
 * by throwing an error whose `code` matches
 * `statusCodes.SIGN_IN_CANCELLED`. The actual string value is platform-
 * dependent (it comes from the native module's `getConstants()`), so
 * we never hard-code it — always compare against the imported
 * constant.
 */
function isGoogleCancelError(err: unknown): boolean {
    return (
        typeof err === "object" &&
        err !== null &&
        "code" in err &&
        (err as { code?: unknown }).code === statusCodes.SIGN_IN_CANCELLED
    );
}
