/**
 * "Trips" — phone equivalent of `apps/web/app/routes/trips.tsx`.
 *
 * Visual model (iOS):
 *   - Native large title "Trips" via `Stack.Screen.headerLargeTitle`
 *     so the title shrinks into the toolbar as the user scrolls — the
 *     canonical iOS Mail / Settings behaviour.
 *   - Header-right `rectangle.portrait.and.arrow.right` SF symbol for
 *     sign-out (uses MaterialCommunityIcons fallback on Android).
 *   - Each saved trip is a tall standalone `<TripCard>` — its own
 *     rounded surface with the full From / To addresses on their own
 *     lines, the trip name as a bold header, and a footer noting when
 *     it was added. We expect users to keep only a handful of trips,
 *     so each cell can breathe rather than packing into a dense
 *     Settings-style row.
 *   - Slot usage is surfaced as a quiet iOS status pill next to the
 *     "Saved trips" section header (e.g. "3 / 5"). The weekly mutation
 *     budget is *not* shown on this screen — it's surfaced only when
 *     the user actually tries to spend it (tapping "New trip" pops an
 *     iOS Alert explaining the cap), so the list stays free of
 *     budget-tracker noise.
 *   - Primary CTA is a floating Liquid Glass pill pinned to the
 *     bottom safe area — on iOS 26+ it's translucent and refracts the
 *     content behind it, on older iOS / Android it's a flat
 *     brand-tinted pill with the same shape and tap target.
 */
import { useCallback } from "react";
import {
    Alert,
    Pressable,
    RefreshControl,
    ScrollView,
    StyleSheet,
    View,
} from "react-native";
import { Stack, useRouter } from "expo-router";
import { ActivityIndicator, Text, Tooltip, useTheme } from "react-native-paper";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
    deleteTrip as sharedDeleteTrip,
    listTrips as sharedListTrips,
    getTripQuota as sharedGetTripQuota,
    type TripSummary,
} from "@time2leave/shared";

import { apiFetch, getApi } from "~/api/client";
import { GlassPill, ScrollEdgeFade } from "~/components/native/Glass";
import { IOSStatusPill } from "~/components/native/StatusPill";
import { Symbol } from "~/components/native/Symbol";

export default function TripList() {
    const theme = useTheme();
    const insets = useSafeAreaInsets();
    const router = useRouter();
    const queryClient = useQueryClient();

    const tripsQuery = useQuery({
        queryKey: ["trips"],
        queryFn: () => sharedListTrips(apiFetch, getApi()),
    });
    const quotaQuery = useQuery({
        queryKey: ["trips", "quota"],
        queryFn: () => sharedGetTripQuota(apiFetch, getApi()),
    });

    const handleDelete = useCallback(
        (trip: TripSummary) => {
            Alert.alert(
                "Delete trip?",
                `Remove "${trip.name ?? trip.origin_address}" from your saved trips?`,
                [
                    { text: "Cancel", style: "cancel" },
                    {
                        text: "Delete",
                        style: "destructive",
                        onPress: async () => {
                            try {
                                await sharedDeleteTrip(apiFetch, getApi(), trip.id);
                                await queryClient.invalidateQueries({
                                    queryKey: ["trips"],
                                });
                                await queryClient.invalidateQueries({
                                    queryKey: ["trips", "quota"],
                                });
                            } catch (err) {
                                Alert.alert(
                                    "Delete failed",
                                    err instanceof Error ? err.message : "Try again.",
                                );
                            }
                        },
                    },
                ],
            );
        },
        [queryClient],
    );

    const quota = quotaQuery.data;
    const trips = tripsQuery.data;
    const slotsUsed = trips?.length ?? quota?.used ?? 0;
    const atSlotLimit = quota != null && slotsUsed >= quota.limit;
    const atMutationLimit =
        quota != null && quota.mutations_used >= quota.mutations_limit;
    // Bottom padding has to clear the floating "New trip" pill (52 px)
    // plus the safe-area inset plus a little breathing room — otherwise
    // the last trip card hides behind the pill on tall phones.
    const PILL_CLEARANCE = 52 + 24;

    // Tapping "New trip" while at a quota limit pops a clear iOS Alert
    // instead of just being silently disabled — users were confused
    // when nothing happened. We only surface the budget at the moment
    // the user actually tries to spend it; no permanent UI noise.
    const handleNewTrip = useCallback(() => {
        if (atSlotLimit && quota) {
            Alert.alert(
                "Trip limit reached",
                `You're using all ${quota.limit} trip slots. Delete a trip to free one up.`,
                [{ text: "OK", style: "default" }],
            );
            return;
        }
        if (atMutationLimit && quota) {
            Alert.alert(
                "Weekly change limit reached",
                `You've made ${quota.mutations_limit} trip changes this week. Each new trip or address edit runs a fresh week of Google Maps lookups, so we cap weekly changes. Older edits roll off automatically — try again in a few days.`,
                [{ text: "OK", style: "default" }],
            );
            return;
        }
        router.push("/trips/new");
    }, [atSlotLimit, atMutationLimit, quota, router]);

    return (
        <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
            {/* Static title + large-title style come from `_layout.tsx`
                so iOS knows them eagerly (back-chevron label, modal
                title). Here we only inject the dynamic header-right
                action. */}
            <Stack.Screen
                options={{
                    headerRight: () => (
                        <Tooltip title="Settings">
                            <Pressable
                                onPress={() => router.push("/trips/settings")}
                                accessibilityRole="button"
                                accessibilityLabel="Open settings"
                                hitSlop={12}
                                style={({ pressed }) => ({
                                    opacity: pressed ? 0.5 : 1,
                                    paddingHorizontal: 4,
                                    paddingVertical: 4,
                                })}
                            >
                                <Symbol
                                    name={{
                                        ios: "gearshape",
                                        android: "cog-outline",
                                    }}
                                    size={22}
                                    color={theme.colors.primary}
                                />
                            </Pressable>
                        </Tooltip>
                    ),
                }}
            />

            <ScrollView
                contentInsetAdjustmentBehavior="automatic"
                contentContainerStyle={{
                    paddingHorizontal: 20,
                    // With the greeting line gone, the "Saved trips"
                    // section header sits directly under the large
                    // title — give it real breathing room (Apple uses
                    // ~16–20 pt below large titles before the first
                    // content block in Mail / Reminders).
                    paddingTop: 16,
                    paddingBottom: insets.bottom + PILL_CLEARANCE,
                    gap: 22,
                }}
                refreshControl={
                    <RefreshControl
                        refreshing={tripsQuery.isFetching && !tripsQuery.isLoading}
                        onRefresh={() => {
                            void tripsQuery.refetch();
                            void quotaQuery.refetch();
                        }}
                        tintColor={theme.colors.primary}
                    />
                }
            >
                {tripsQuery.isLoading ? (
                    <ActivityIndicator
                        size="small"
                        color={theme.colors.onSurfaceVariant}
                        style={{ marginTop: 24 }}
                    />
                ) : tripsQuery.isError ? (
                    <Text style={{ color: theme.colors.error }}>
                        Couldn&apos;t load trips:{" "}
                        {tripsQuery.error instanceof Error
                            ? tripsQuery.error.message
                            : "unknown error"}
                    </Text>
                ) : trips && trips.length > 0 ? (
                    <Section
                        header="Saved trips"
                        accessory={
                            quota ? (
                                <IOSStatusPill
                                    icon={{
                                        ios: "bookmark.fill",
                                        android: "bookmark",
                                    }}
                                    label={`${slotsUsed} / ${quota.limit}`}
                                    tone={atSlotLimit ? "warning" : "default"}
                                />
                            ) : null
                        }
                    >
                        <View style={{ gap: 12 }}>
                            {trips.map((trip) => (
                                <TripCard
                                    key={trip.id}
                                    trip={trip}
                                    onPress={() =>
                                        router.push({
                                            pathname: "/trips/[tripId]",
                                            params: { tripId: trip.id },
                                        })
                                    }
                                    onDelete={() => handleDelete(trip)}
                                />
                            ))}
                        </View>
                    </Section>
                ) : (
                    <EmptyState />
                )}
            </ScrollView>

            {/* Soft fade behind the floating CTA so list rows
                disappear into the background as they scroll past the
                pill — Apple's iOS 26 chrome pattern (Notes, Reminders).
                Sits below the pill in z-order, doesn't intercept taps. */}
            <ScrollEdgeFade edge="bottom" height={insets.bottom + 96} />

            {/* Floating Liquid Glass primary CTA, pinned over the
                scroll view. Keeps "New trip" reachable with one thumb
                no matter how long the list is. */}
            <View
                pointerEvents="box-none"
                style={{
                    position: "absolute",
                    left: 20,
                    right: 20,
                    bottom: insets.bottom + 12,
                }}
            >
                <GlassPill
                    tone="accent"
                    onPress={handleNewTrip}
                    accessibilityLabel="New trip"
                >
                    <Symbol
                        name={{ ios: "plus", android: "plus" }}
                        size={18}
                        color={theme.colors.onBackground}
                        weight="bold"
                    />
                    <Text
                        style={{
                            color: theme.colors.onBackground,
                            fontWeight: "700",
                            fontSize: 16,
                            letterSpacing: 0.2,
                        }}
                    >
                        New trip
                    </Text>
                </GlassPill>
            </View>
        </View>
    );
}

/**
 * iOS-style section header with an optional trailing accessory
 * (typically a status pill). Matches `<GroupedSection>` from
 * `~/components/native/GroupedList` but adds the right-side accessory
 * slot for status indicators that callers want next to the label.
 */
function Section({
    header,
    accessory,
    children,
}: {
    header: string;
    accessory?: React.ReactNode;
    children?: React.ReactNode;
}) {
    const theme = useTheme();
    return (
        <View style={{ gap: 8 }}>
            <View
                style={{
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginLeft: 14,
                    marginRight: 4,
                }}
            >
                <Text
                    style={{
                        color: theme.colors.onSurfaceVariant,
                        textTransform: "uppercase",
                        fontSize: 12,
                        letterSpacing: 0.7,
                        fontWeight: "600",
                    }}
                >
                    {header}
                </Text>
                {accessory}
            </View>
            {children}
        </View>
    );
}

/**
 * Tall trip card — the "saved trip" cell on the trips list.
 *
 * Designed for a small saved-trips list (we don't expect users to have
 * many) so each cell can breathe and show the *full* From / To
 * addresses, the trip name, the date it was added, and explicit
 * disclosure + delete affordances. This is the iOS Maps "Saved
 * Guides" / Notes "Folder card" pattern: one rounded surface per
 * item, generous padding, addresses on their own lines.
 *
 * Layout:
 *
 *     ┌─────────────────────────────────────┐
 *     │ [icon] Title                  🗑  ›  │
 *     │ ─────────────────────────────────── │
 *     │ 🏠  From                            │
 *     │     <full origin address>           │
 *     │                                     │
 *     │ 📍  To                              │
 *     │     <full destination address>      │
 *     │ ─────────────────────────────────── │
 *     │ 📅 Added Mar 12                     │
 *     └─────────────────────────────────────┘
 */
function TripCard({
    trip,
    onPress,
    onDelete,
}: {
    trip: TripSummary;
    onPress: () => void;
    onDelete: () => void;
}) {
    const theme = useTheme();
    const dividerColor = theme.dark
        ? "rgba(255,255,255,0.08)"
        : "rgba(60,60,67,0.18)";
    const title = trip.name?.trim() || "Untitled trip";
    const addedLabel = formatAddedDate(trip.created_at);

    return (
        <Pressable
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={`Open trip ${title}`}
            android_ripple={{ color: theme.colors.surfaceVariant }}
            style={({ pressed }) => ({
                opacity: pressed ? 0.85 : 1,
                borderRadius: 18,
                backgroundColor: theme.colors.surface,
                borderWidth: StyleSheet.hairlineWidth,
                borderColor: theme.dark
                    ? "rgba(255,255,255,0.08)"
                    : "rgba(0,0,0,0.06)",
                shadowColor: "#000",
                shadowOpacity: theme.dark ? 0.35 : 0.06,
                shadowRadius: 12,
                shadowOffset: { width: 0, height: 4 },
                elevation: 2,
            })}
        >
            <View style={{ padding: 18, gap: 14 }}>
                <View
                    style={{
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 12,
                    }}
                >
                    <View
                        style={{
                            width: 38,
                            height: 38,
                            borderRadius: 10,
                            alignItems: "center",
                            justifyContent: "center",
                            backgroundColor: theme.colors.primary,
                        }}
                    >
                        <Symbol
                            name={{
                                ios: "car.fill",
                                android: "map-marker-distance",
                            }}
                            size={20}
                            color="#ffffff"
                            weight="semibold"
                        />
                    </View>
                    <Text
                        style={{
                            flex: 1,
                            color: theme.colors.onSurface,
                            fontWeight: "700",
                            fontSize: 19,
                            letterSpacing: -0.2,
                        }}
                        numberOfLines={2}
                    >
                        {title}
                    </Text>
                    <Pressable
                        onPress={onDelete}
                        accessibilityRole="button"
                        accessibilityLabel={`Delete trip ${title}`}
                        hitSlop={12}
                        style={({ pressed }) => ({
                            padding: 6,
                            opacity: pressed ? 0.5 : 1,
                        })}
                    >
                        <Symbol
                            name={{
                                ios: "trash",
                                android: "trash-can-outline",
                            }}
                            size={18}
                            color={theme.colors.onSurfaceVariant}
                        />
                    </Pressable>
                    <Symbol
                        name={{
                            ios: "chevron.right",
                            android: "chevron-right",
                        }}
                        size={13}
                        color={theme.colors.onSurfaceVariant}
                        weight="semibold"
                    />
                </View>

                <View
                    style={{
                        height: StyleSheet.hairlineWidth,
                        backgroundColor: dividerColor,
                    }}
                />

                <View style={{ gap: 12 }}>
                    <AddressLine
                        kind="from"
                        address={trip.origin_address}
                    />
                    <AddressLine
                        kind="to"
                        address={trip.destination_address}
                    />
                </View>

                {addedLabel ? (
                    <>
                        <View
                            style={{
                                height: StyleSheet.hairlineWidth,
                                backgroundColor: dividerColor,
                            }}
                        />
                        <View
                            style={{
                                flexDirection: "row",
                                alignItems: "center",
                                gap: 6,
                            }}
                        >
                            <Symbol
                                name={{
                                    ios: "calendar",
                                    android: "calendar",
                                }}
                                size={13}
                                color={theme.colors.onSurfaceVariant}
                            />
                            <Text
                                style={{
                                    color: theme.colors.onSurfaceVariant,
                                    fontSize: 13,
                                    fontWeight: "500",
                                }}
                            >
                                Added {addedLabel}
                            </Text>
                        </View>
                    </>
                ) : null}
            </View>
        </Pressable>
    );
}

/**
 * Single labelled address row inside a `TripCard`. Renders the small
 * uppercase "FROM" / "TO" tag and the full address on its own line so
 * long addresses can wrap naturally instead of being truncated like
 * they were in the old single-line `GroupedRow` subtitle.
 */
function AddressLine({
    kind,
    address,
}: {
    kind: "from" | "to";
    address: string;
}) {
    const theme = useTheme();
    const isFrom = kind === "from";
    const symbolName = isFrom
        ? ({ ios: "house.fill", android: "home-outline" } as const)
        : ({ ios: "mappin.circle.fill", android: "map-marker" } as const);
    const tint = isFrom ? theme.colors.primary : theme.colors.secondary;
    return (
        <View style={{ flexDirection: "row", gap: 12 }}>
            <View style={{ width: 22, alignItems: "center", paddingTop: 2 }}>
                <Symbol name={symbolName} size={18} color={tint} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
                <Text
                    style={{
                        color: theme.colors.onSurfaceVariant,
                        fontSize: 11,
                        fontWeight: "600",
                        letterSpacing: 0.6,
                        textTransform: "uppercase",
                    }}
                >
                    {isFrom ? "From" : "To"}
                </Text>
                <Text
                    style={{
                        color: theme.colors.onSurface,
                        fontSize: 15,
                        lineHeight: 20,
                    }}
                >
                    {address}
                </Text>
            </View>
        </View>
    );
}

/**
 * iOS-style empty state — centered SF symbol + clear short title +
 * one-sentence body. We deliberately don't add a CTA here because the
 * floating "New trip" Liquid Glass pill is already the primary
 * action; duplicating it would just create two near-identical buttons
 * on a mostly-empty screen.
 */
function EmptyState() {
    const theme = useTheme();
    return (
        <View
            style={{
                paddingTop: 56,
                paddingHorizontal: 12,
                alignItems: "center",
                gap: 12,
            }}
        >
            <Symbol
                name={{
                    ios: "map",
                    android: "map-search-outline",
                }}
                size={56}
                color={theme.colors.onSurfaceVariant}
                weight="light"
            />
            <Text
                variant="titleMedium"
                style={{
                    fontWeight: "700",
                    color: theme.colors.onBackground,
                    textAlign: "center",
                }}
            >
                No trips yet
            </Text>
            <Text
                variant="bodyMedium"
                style={{
                    color: theme.colors.onSurfaceVariant,
                    textAlign: "center",
                    lineHeight: 20,
                }}
            >
                Tap New trip to save a route — we&apos;ll start sampling drive
                times every 15 minutes for the whole week.
            </Text>
        </View>
    );
}

/**
 * Format a trip's `created_at` ISO string for the card footer. Uses
 * the user's locale for the month abbreviation and includes the year
 * only when the trip wasn't added in the current calendar year — keeps
 * recent trips short ("Mar 12") and older ones unambiguous
 * ("Mar 12, 2024"). Returns `null` for missing / unparseable input
 * so the caller can hide the row entirely instead of showing
 * "Added Invalid Date".
 */
function formatAddedDate(iso: string | null): string | null {
    if (!iso) return null;
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return null;
    const now = new Date();
    const sameYear = dt.getFullYear() === now.getFullYear();
    return dt.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: sameYear ? undefined : "numeric",
    });
}
