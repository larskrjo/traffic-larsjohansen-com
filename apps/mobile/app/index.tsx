/**
 * Splash + sign-in screen (signed-out only).
 *
 * Structure mirrors the iOS first-run pattern (e.g. Apple's "Welcome
 * to Freeform" sheet): a tall hero preview that *shows what the
 * product is* sits at the top, a compact brand + headline + paragraph
 * block sits below it, and a single full-width pill CTA is pinned to
 * the bottom safe-area inset.
 *
 * Why a `View` (not `ScrollView`)?
 * The whole screen fits inside one device viewport on every supported
 * iPhone (SE 3rd-gen and up) and Android phone — there is *nothing*
 * to scroll to, so a ScrollView would only enable iOS's rubber-band
 * bounce that makes the screen feel like an unfinished web page.
 * The hero card is the single flexible region: it absorbs whatever
 * vertical slack the device has, so the same layout reads well from
 * 5.4" SE up to 6.9" Pro Max without bottoming out.
 *
 * Sign-in is gated strictly by `EXPO_PUBLIC_APP_ENV`:
 *   - `local` → only the dev-login button is shown. Posts to
 *     /api/v1/auth/dev-login with `EXPO_PUBLIC_DEV_LOGIN_EMAIL`,
 *     which must be on the backend's auth allowlist.
 *   - `prod`  → only the native Google Sign-In button is shown.
 *
 * Authenticated users are redirected straight to /trips so this
 * screen never flashes for someone who already has a session.
 */
import { useState } from "react";
import { View } from "react-native";
import { Redirect } from "expo-router";
import { Text, useTheme } from "react-native-paper";
import { LinearGradient } from "expo-linear-gradient";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colorFor, formatSlot12h, minutesLabel } from "@time2leave/shared";

import { AppleSignInButton } from "~/auth/AppleSignInButton";
import { useAuth } from "~/auth/AuthProvider";
import { GoogleSignInButton } from "~/auth/GoogleSignInButton";
import { Loading } from "~/components/Loading";
import { Wordmark } from "~/components/Wordmark";
import { GlassPill } from "~/components/native/Glass";
import { Symbol } from "~/components/native/Symbol";
import { requireEnv } from "~/config/env";
import { BRAND_GRADIENT } from "~/theme";

export default function Splash() {
    const theme = useTheme();
    const insets = useSafeAreaInsets();
    const { status, signInDev } = useAuth();
    const env = requireEnv();

    // Tri-state sign-in feedback. The two error states map 1:1 to
    // the two callbacks each provider button exposes — see
    // {Apple,Google}SignInButton.tsx for the full UX rule.
    //   "none"       -> default invite-only disclaimer.
    //   "allowlist"  -> backend 403: provider authenticated the user
    //                   but the email isn't on the invite list.
    //   "unexpected" -> any other backend/network/provider failure
    //                   (401, 5xx, offline, missing Play services,
    //                   ERR_REQUEST_FAILED, ...). We don't drill
    //                   into the cause for the user — they'd just
    //                   see noise — but we *do* tell them the
    //                   attempt failed instead of silently
    //                   dismissing, which is what masked the prod
    //                   `apple_sub` schema-drift outage in TestFlight.
    // User cancels stay silent inside the buttons themselves.
    type SignInError = "none" | "allowlist" | "unexpected";
    const [signInError, setSignInError] = useState<SignInError>("none");

    if (status === "loading") return <Loading label="Restoring session…" />;
    if (status === "authenticated") return <Redirect href="/trips" />;

    return (
        <View
            style={{
                flex: 1,
                backgroundColor: theme.colors.background,
                paddingTop: insets.top,
                paddingBottom: insets.bottom + 16,
                paddingHorizontal: 20,
            }}
        >
            {/* One vertically-centered composition: hero card → brand
                stack → CTA → disclaimer. Putting the CTA *inside* the
                centered group (instead of pinning it to the bottom
                safe-area inset) keeps the title in roughly the same
                vertical position as before *and* lifts the sign-in
                button up so it sits right under the description —
                the obvious next action, not a floating afterthought
                near the home indicator. */}
            <View
                style={{
                    flex: 1,
                    justifyContent: "center",
                    gap: 24,
                }}
            >
                <HeatmapPreviewCard />

                <View style={{ gap: 12, alignItems: "center" }}>
                    <Wordmark size={44} />
                    <Text
                        variant="headlineSmall"
                        style={{
                            fontWeight: "800",
                            textAlign: "center",
                            letterSpacing: -0.5,
                            color: theme.colors.onBackground,
                        }}
                    >
                        Know exactly when to leave.
                    </Text>
                    <Text
                        variant="bodyMedium"
                        style={{
                            color: theme.colors.onSurfaceVariant,
                            textAlign: "center",
                            lineHeight: 20,
                            paddingHorizontal: 8,
                        }}
                    >
                        Save a trip and we measure real drive times every
                        15 minutes for the whole week — both directions.
                    </Text>
                </View>

                <View style={{ width: "100%", gap: 10 }}>
                    {env.appEnv === "prod" ? (
                        <>
                            {/* Apple HIG mandates that "Sign in with
                                Apple" is at least as prominent as
                                other third-party sign-in options on
                                iOS, so it sits above Google. The
                                button itself returns null on Android,
                                where Google remains the only path. */}
                            <AppleSignInButton
                                style={CTA_BUTTON_STYLE}
                                onAttemptStart={() => setSignInError("none")}
                                onAllowlistRejected={() =>
                                    setSignInError("allowlist")
                                }
                                onUnexpectedError={() =>
                                    setSignInError("unexpected")
                                }
                            />
                            <GoogleSignInButton
                                style={CTA_BUTTON_STYLE}
                                contentStyle={CTA_BUTTON_CONTENT_STYLE}
                                labelStyle={CTA_BUTTON_LABEL_STYLE}
                                onAttemptStart={() => setSignInError("none")}
                                onAllowlistRejected={() =>
                                    setSignInError("allowlist")
                                }
                                onUnexpectedError={() =>
                                    setSignInError("unexpected")
                                }
                            />
                        </>
                    ) : (
                        <GlassPill
                            tone="accent"
                            onPress={() => {
                                void signInDev(env.devLoginEmail, "Dev User");
                            }}
                            accessibilityLabel={`Continue as ${env.devLoginEmail}`}
                        >
                            <Symbol
                                name={{
                                    ios: "person.crop.circle.badge.checkmark",
                                    android: "account-arrow-right",
                                }}
                                size={18}
                                color={theme.colors.onBackground}
                                weight="semibold"
                            />
                            <Text
                                style={{
                                    color: theme.colors.onBackground,
                                    fontSize: 16,
                                    fontWeight: "700",
                                    letterSpacing: 0.2,
                                }}
                            >
                                Continue as {env.devLoginEmail}
                            </Text>
                        </GlassPill>
                    )}

                    {/* Subtext slot under the CTAs: defaults to the
                        invite-only disclaimer; swaps to a tinted
                        error message when the provider button
                        signalled a failure. Each branch is a single
                        line so the user reads exactly one thing at
                        a time. */}
                    {signInError === "allowlist" ? (
                        <Text
                            variant="bodySmall"
                            style={{
                                color: theme.colors.error,
                                textAlign: "center",
                                paddingHorizontal: 8,
                                fontWeight: "600",
                            }}
                            accessibilityLiveRegion="polite"
                        >
                            You're not on the invite list. Ask the owner
                            to add you and try again.
                        </Text>
                    ) : signInError === "unexpected" ? (
                        <Text
                            variant="bodySmall"
                            style={{
                                color: theme.colors.error,
                                textAlign: "center",
                                paddingHorizontal: 8,
                                fontWeight: "600",
                            }}
                            accessibilityLiveRegion="polite"
                        >
                            Couldn't sign in. Check your connection and
                            try again.
                        </Text>
                    ) : (
                        <Text
                            variant="bodySmall"
                            style={{
                                color: theme.colors.onSurfaceVariant,
                                textAlign: "center",
                                paddingHorizontal: 8,
                            }}
                        >
                            {env.appEnv === "prod"
                                ? "Invite-only — your email must be on the allowlist."
                                : "Dev mode — the email above must be on the backend's allowlist."}
                        </Text>
                    )}
                </View>
            </View>
        </View>
    );
}

/**
 * Big rounded "pill" CTA — Apple-style first-run button. We share the
 * same shape across both auth paths (Google + dev-login) so the
 * sign-in moment looks identical regardless of which build target the
 * user is in.
 *
 * `CTA_BUTTON_LABEL_STYLE` is sized to match Apple's
 * `ASAuthorizationAppleIDButton` typography. Apple's framework
 * auto-scales the button label as a function of `cornerRadius`
 * (roughly `cornerRadius * 0.7`), so at our 28pt corner radius the
 * Apple label renders at ≈19pt SF Pro *medium*. There is no public
 * API to override that — the only way to make "Continue with Google"
 * read as a balanced pair next to it is to size our custom Google
 * pill to the same metrics. Plain semibold (`"600"`) here looked
 * visibly heavier than Apple's label and made the two CTAs feel
 * mismatched, so we use medium (`"500"`) for the same reason.
 */
const CTA_BUTTON_STYLE = { borderRadius: 28 } as const;
const CTA_BUTTON_CONTENT_STYLE = { paddingVertical: 10 } as const;
const CTA_BUTTON_LABEL_STYLE = {
    fontSize: 20,
    fontWeight: "500" as const,
    letterSpacing: 0,
};

/**
 * Mini-heatmap preview that doubles as the splash hero. Shows the
 * exact visual the user will get inside the app — five weekdays of
 * fake-but-plausible drive-time samples (slow morning rush, fast
 * midday, slow evening rush) coloured by the *real* `colorFor`
 * function from `@time2leave/shared`, so the gradient on this card
 * is byte-identical to the one they'll see on their first trip.
 *
 * The card is wrapped in a soft brand-gradient backdrop and a thin
 * outline so it reads as "the product, miniaturised" rather than
 * marketing chrome.
 */
function HeatmapPreviewCard() {
    const theme = useTheme();

    // Five-day × five-slot fake samples. Numbers are minutes; the
    // pattern is a typical commute: morning rush slow → midday fast
    // → evening rush slow. The grid only has to *feel* real on first
    // glance; once the user signs in they get their own data.
    const PREVIEW_SLOTS = ["07:30", "09:00", "12:00", "15:30", "17:30"] as const;
    const PREVIEW_DATA = [
        { day: "Mon", values: [38, 22, 14, 18, 41] },
        { day: "Tue", values: [36, 21, 13, 19, 39] },
        { day: "Wed", values: [40, 24, 15, 17, 43] },
        { day: "Thu", values: [37, 23, 14, 20, 38] },
        { day: "Fri", values: [42, 26, 16, 22, 47] },
    ] as const;
    const allValues = PREVIEW_DATA.flatMap((row) => row.values);
    const minMinutes = Math.min(...allValues);
    const maxMinutes = Math.max(...allValues);

    return (
        <View style={{ width: "100%", alignItems: "center" }}>
            {/* Soft gradient halo behind the card — same blue→orange
                ramp as the wordmark, knocked back to ~10% so it tints
                the corners without competing with the cells. */}
            <LinearGradient
                colors={[`${BRAND_GRADIENT[0]}1A`, `${BRAND_GRADIENT[1]}1A`]}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={{
                    width: "100%",
                    borderRadius: 24,
                    padding: 14,
                }}
            >
                <View
                    style={{
                        backgroundColor: theme.colors.surface,
                        borderRadius: 16,
                        borderWidth: 1,
                        borderColor: theme.colors.outline,
                        padding: 12,
                        gap: 8,
                    }}
                >
                    {/* Faux "trip card" header so the preview reads as a
                        real saved trip, not just a swatch grid. */}
                    <View
                        style={{
                            flexDirection: "row",
                            alignItems: "center",
                            justifyContent: "space-between",
                            paddingHorizontal: 4,
                            paddingBottom: 4,
                        }}
                    >
                        <Text
                            variant="labelLarge"
                            style={{ fontWeight: "800", color: theme.colors.onSurface }}
                        >
                            Home → Office
                        </Text>
                        <View
                            style={{
                                paddingHorizontal: 8,
                                paddingVertical: 2,
                                borderRadius: 999,
                                backgroundColor: `${BRAND_GRADIENT[0]}1F`,
                            }}
                        >
                            <Text
                                variant="labelSmall"
                                style={{
                                    color: BRAND_GRADIENT[0],
                                    fontWeight: "700",
                                    letterSpacing: 0.4,
                                }}
                            >
                                THIS WEEK
                            </Text>
                        </View>
                    </View>

                    {/* Column header — slot times across the top. */}
                    <View style={{ flexDirection: "row", gap: 4, paddingLeft: 36 }}>
                        {PREVIEW_SLOTS.map((slot) => (
                            <Text
                                key={slot}
                                variant="labelSmall"
                                style={{
                                    flex: 1,
                                    textAlign: "center",
                                    color: theme.colors.onSurfaceVariant,
                                    fontVariant: ["tabular-nums"],
                                }}
                            >
                                {formatSlot12h(slot)}
                            </Text>
                        ))}
                    </View>

                    {/* The grid itself. */}
                    <View style={{ gap: 4 }}>
                        {PREVIEW_DATA.map((row) => (
                            <View
                                key={row.day}
                                style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
                            >
                                <Text
                                    variant="labelMedium"
                                    style={{
                                        width: 32,
                                        fontWeight: "800",
                                        color: theme.colors.onSurface,
                                    }}
                                >
                                    {row.day}
                                </Text>
                                {row.values.map((minutes, i) => (
                                    <View
                                        key={`${row.day}-${i}`}
                                        style={{
                                            flex: 1,
                                            paddingVertical: 8,
                                            borderRadius: 8,
                                            alignItems: "center",
                                            backgroundColor: colorFor(
                                                minutes,
                                                minMinutes,
                                                maxMinutes,
                                            ),
                                        }}
                                    >
                                        <Text
                                            style={{
                                                fontSize: 11,
                                                fontWeight: "800",
                                                color: "#0b1020",
                                                fontVariant: ["tabular-nums"],
                                            }}
                                        >
                                            {minutesLabel(minutes)}
                                        </Text>
                                    </View>
                                ))}
                            </View>
                        ))}
                    </View>

                    {/* Tiny legend so first-time viewers know what the
                        colour scale means without having to guess. */}
                    <View
                        style={{
                            flexDirection: "row",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: 6,
                            paddingTop: 4,
                        }}
                    >
                        <Text
                            variant="labelSmall"
                            style={{ color: theme.colors.onSurfaceVariant }}
                        >
                            Faster
                        </Text>
                        <LinearGradient
                            colors={[
                                colorFor(minMinutes, minMinutes, maxMinutes),
                                colorFor(
                                    (minMinutes + maxMinutes) / 2,
                                    minMinutes,
                                    maxMinutes,
                                ),
                                colorFor(maxMinutes, minMinutes, maxMinutes),
                            ]}
                            start={{ x: 0, y: 0 }}
                            end={{ x: 1, y: 0 }}
                            style={{
                                height: 6,
                                width: 96,
                                borderRadius: 3,
                            }}
                        />
                        <Text
                            variant="labelSmall"
                            style={{ color: theme.colors.onSurfaceVariant }}
                        >
                            Slower
                        </Text>
                    </View>
                </View>
            </LinearGradient>
        </View>
    );
}
