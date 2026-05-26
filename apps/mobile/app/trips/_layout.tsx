/**
 * Auth-gated layout for everything under `/trips`.
 *
 * Anonymous users get bounced to the splash; authenticated users see
 * the trip list / detail screens.
 *
 * Why titles are declared *here* (not in each screen body):
 *   `<Stack.Screen options={...}>` rendered inside a screen component
 *   only fires after that screen mounts, which is too late for two
 *   things iOS needs eagerly:
 *
 *     1. The back-chevron label on the *next* screen — iOS reads the
 *        previous screen's title at the moment it starts the push
 *        transition, so if "Trips" isn't registered yet, the chevron
 *        appears with no label and pops in late.
 *
 *     2. The modal title — iOS shows the modal's nav bar before the
 *        modal screen finishes rendering, so the route file name
 *        ("new") flashes as the title before the in-screen Stack.Screen
 *        override applies.
 *
 *   Registering them on the parent `<Stack>` ahead of time fixes both:
 *   the title is known before the transition begins.
 *
 * Why the header uses Liquid Glass + transparent + custom background:
 *   We want Apple's iOS 26 scroll-edge behaviour: the bar starts
 *   nearly invisible at the top of the scroll and gradually frosts
 *   over content as the user scrolls past it — the same fade
 *   language we use at the bottom edge with `ScrollEdgeFade`.
 *
 *   `headerBlurEffect: "systemChromeMaterial*"` produced a fixed
 *   gray frosted material that never matched our brand background,
 *   so we drop it. Instead we set `headerTransparent: true` (so
 *   content scrolls *under* the bar) and inject a `GlassNavBackground`
 *   via the `headerBackground` slot — that wrapper renders a real
 *   `GlassView` from `expo-glass-effect` on iOS 26+ (Apple's actual
 *   Liquid Glass material, which refracts and tints content behind
 *   it), and falls back to a soft gradient on older iOS / Android so
 *   the visual still reads as a fading chrome strip.
 *
 *   Net result: scrolling under the nav bar dissolves content into
 *   the chrome instead of cutting it off at a flat line.
 *
 * Android falls back to the standard Material 3 top-bar that
 * react-native-screens renders — `headerLargeTitle` is a no-op there
 * but the soft-fade fallback in `GlassNavBackground` still applies.
 */
import { Redirect, Stack } from "expo-router";
import { Platform } from "react-native";
import { useTheme } from "react-native-paper";

import { useAuth } from "~/auth/AuthProvider";
import { Loading } from "~/components/Loading";
import { GlassNavBackground } from "~/components/native/Glass";

export default function TripsLayout() {
    const theme = useTheme();
    const { status } = useAuth();
    if (status === "loading") return <Loading />;
    if (status !== "authenticated") return <Redirect href="/" />;

    const isIos = Platform.OS === "ios";

    return (
        <Stack
            screenOptions={{
                headerShown: true,
                headerLargeTitle: isIos,
                // Transparent so scroll content can pass *under* the
                // bar — the precondition for the Liquid Glass /
                // soft-fade chrome effect to be visible at all.
                headerTransparent: isIos,
                // Liquid Glass on iOS 26+, soft fade fallback
                // elsewhere. See `GlassNavBackground` for details.
                headerBackground: () => <GlassNavBackground />,
                headerLargeTitleShadowVisible: false,
                headerShadowVisible: false,
                headerTintColor: theme.colors.primary,
                headerTitleStyle: {
                    fontWeight: "600",
                    color: theme.colors.onBackground,
                },
                headerLargeTitleStyle: {
                    // SF Pro Display Bold — matches Apple's native
                    // weight for `prefersLargeTitles`. 800 read as
                    // heavier-than-system in side-by-side comparisons
                    // with Mail / Settings / Reminders.
                    fontWeight: "700",
                    color: theme.colors.onBackground,
                },
                contentStyle: {
                    backgroundColor: theme.colors.background,
                },
                animation: "default",
            }}
        >
            {/* Per-screen options registered ahead of time so iOS
                knows each screen's title at navigation start. The
                screens themselves can still override these via their
                own <Stack.Screen> calls (e.g. the trip detail injects
                the trip's name as a dynamic title). */}
            <Stack.Screen
                name="index"
                options={{
                    title: "Trips",
                }}
            />
            <Stack.Screen
                name="[tripId]"
                options={{
                    // Placeholder — the screen body sets the real
                    // title once it's loaded the trip. This default
                    // keeps the bar from flashing the route segment
                    // (`[tripId]`) for the half-frame before the
                    // dynamic title settles in.
                    title: "Trip",
                    headerBackTitle: "Trips",
                }}
            />
            <Stack.Screen
                name="new"
                options={{
                    title: "New Trip",
                    presentation: "modal",
                    headerLargeTitle: false,
                }}
            />
            <Stack.Screen
                name="settings"
                options={{
                    title: "Settings",
                    presentation: "modal",
                    headerLargeTitle: false,
                }}
            />
        </Stack>
    );
}
