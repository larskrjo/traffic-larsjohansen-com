/**
 * Settings — iOS-style modal screen presented from the trips header.
 *
 * Two sections, mirroring the iOS Settings pattern of "informational
 * rows up top, destructive actions in their own clearly-labelled
 * section at the bottom":
 *
 *   1. **Account** — display-only name + email, plus a "Sign out" row.
 *      This is just the existing sign-out button that used to live in
 *      the trips-list header, moved into a screen where it can sit
 *      alongside other account-management actions.
 *
 *   2. **Danger zone** — "Delete account". Hits
 *      `DELETE /api/v1/me` on the backend, which CASCADE-drops the
 *      user's trips, samples, and mutation log; the local
 *      `AuthProvider.deleteAccount` mirror clears the bearer token
 *      and flips status to anonymous, which makes the route guard in
 *      `app/trips/_layout.tsx` redirect to the splash on the next
 *      render.
 *
 * Why this exists: Apple App Review Guideline 5.1.1(v) requires every
 * app with account creation (which we have via Sign in with Apple) to
 * also offer in-app account deletion. Submission gets auto-rejected
 * without it. The web app has the matching flow at
 * `apps/web/app/routes/settings.tsx`.
 *
 * Destructive-action UX rule (matches iOS native double-confirm
 * pattern, e.g. "Delete iCloud Account"):
 *   tap row → first Alert: "Delete account?" + Cancel / Delete Account
 *           → second Alert: "This can't be undone." + Cancel / Delete
 *           → call `deleteAccount()`. Errors show a third Alert and
 *             leave the local state intact so the user can retry.
 */
import { useState, type ComponentProps } from "react";
import { Alert, Platform, Pressable, ScrollView, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { ActivityIndicator, Text, useTheme } from "react-native-paper";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "~/auth/AuthProvider";
import { Symbol } from "~/components/native/Symbol";

type SymbolName = ComponentProps<typeof Symbol>["name"];

export default function Settings() {
    const theme = useTheme();
    const insets = useSafeAreaInsets();
    const router = useRouter();
    const { user, signOut, deleteAccount } = useAuth();
    const [busy, setBusy] = useState(false);

    const handleSignOut = () => {
        // Sign-out is fire-and-forget — `signOut` swallows errors,
        // clears local state synchronously, and the route guard
        // redirects to the splash on the next render.
        Alert.alert(
            "Sign out?",
            "You can sign back in any time with the same Apple ID or Google account.",
            [
                { text: "Cancel", style: "cancel" },
                {
                    text: "Sign out",
                    style: "destructive",
                    onPress: () => {
                        void signOut();
                    },
                },
            ],
        );
    };

    const handleDelete = () => {
        // First confirm — what the user is about to do, in plain
        // English. iOS HIG: state the consequence, then the action.
        Alert.alert(
            "Delete account?",
            "This will permanently delete your account, all your saved trips, and every drive-time sample we've collected for them.",
            [
                { text: "Cancel", style: "cancel" },
                {
                    text: "Delete Account",
                    style: "destructive",
                    onPress: () => {
                        // Second confirm — the "this can't be undone"
                        // step iOS uses for terminal destructive
                        // actions (e.g. Erase iPhone, Delete iCloud
                        // Account). Two taps to avoid a fat-fingered
                        // catastrophe; not more than two, because
                        // anything beyond that reads as the app
                        // begging the user not to leave.
                        Alert.alert(
                            "Are you sure?",
                            "This can't be undone. Your trips and history can't be recovered.",
                            [
                                { text: "Cancel", style: "cancel" },
                                {
                                    text: "Delete",
                                    style: "destructive",
                                    onPress: async () => {
                                        setBusy(true);
                                        try {
                                            await deleteAccount();
                                            // No `router.replace`
                                            // needed — the auth
                                            // status flipped to
                                            // anonymous inside
                                            // `deleteAccount`, so the
                                            // trips _layout guard
                                            // redirects to "/" on the
                                            // next render.
                                        } catch (err) {
                                            setBusy(false);
                                            Alert.alert(
                                                "Couldn't delete account",
                                                err instanceof Error
                                                    ? err.message
                                                    : "Check your connection and try again.",
                                            );
                                        }
                                    },
                                },
                            ],
                        );
                    },
                },
            ],
        );
    };

    return (
        <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
            <Stack.Screen
                options={{
                    headerLeft: () => (
                        <Pressable
                            onPress={() => router.back()}
                            accessibilityRole="button"
                            accessibilityLabel="Done"
                            hitSlop={12}
                            disabled={busy}
                            style={({ pressed }) => ({
                                opacity: pressed || busy ? 0.5 : 1,
                                paddingHorizontal: 4,
                                paddingVertical: 4,
                            })}
                        >
                            <Text
                                style={{
                                    color: theme.colors.primary,
                                    fontSize: 17,
                                    fontWeight: "600",
                                }}
                            >
                                Done
                            </Text>
                        </Pressable>
                    ),
                }}
            />

            <ScrollView
                contentInsetAdjustmentBehavior="automatic"
                contentContainerStyle={{
                    paddingHorizontal: 20,
                    paddingTop: 12,
                    paddingBottom: insets.bottom + 32,
                    gap: 28,
                }}
            >
                <SettingsSection label="ACCOUNT">
                    <SettingsInfoRow
                        label="Name"
                        value={user?.name ?? "—"}
                        isFirst
                    />
                    <SettingsInfoRow label="Email" value={user?.email ?? "—"} />
                    <SettingsActionRow
                        label="Sign out"
                        icon={{ ios: "rectangle.portrait.and.arrow.right", android: "logout" }}
                        onPress={handleSignOut}
                        isLast
                    />
                </SettingsSection>

                <SettingsSection
                    label="DANGER ZONE"
                    caption="Deleting your account permanently removes your profile, every saved trip, and the full drive-time history we've collected for those trips. This can't be undone."
                >
                    <SettingsActionRow
                        label={busy ? "Deleting…" : "Delete account"}
                        icon={{ ios: "trash", android: "trash-can-outline" }}
                        onPress={busy ? undefined : handleDelete}
                        tone="destructive"
                        rightAdornment={
                            busy ? (
                                <ActivityIndicator
                                    size="small"
                                    color={theme.colors.error}
                                />
                            ) : undefined
                        }
                        isFirst
                        isLast
                    />
                </SettingsSection>
            </ScrollView>
        </View>
    );
}

// --- Building blocks ----------------------------------------------------
//
// Lightweight iOS-Settings-style rows. We don't use a third-party list
// library because the screen only has 4 rows total — pulling in
// react-native-elements / paper's List for that would be heavier than
// the screen itself.

function SettingsSection({
    label,
    caption,
    children,
}: {
    label: string;
    caption?: string;
    children: React.ReactNode;
}) {
    const theme = useTheme();
    return (
        <View style={{ gap: 8 }}>
            <Text
                variant="labelSmall"
                style={{
                    color: theme.colors.onSurfaceVariant,
                    paddingHorizontal: 16,
                    letterSpacing: 0.6,
                    fontWeight: "600",
                }}
            >
                {label}
            </Text>
            <View
                style={{
                    backgroundColor: theme.colors.surface,
                    borderRadius: 14,
                    overflow: "hidden",
                    borderWidth: 1,
                    borderColor: theme.colors.outlineVariant,
                }}
            >
                {children}
            </View>
            {caption ? (
                <Text
                    variant="bodySmall"
                    style={{
                        color: theme.colors.onSurfaceVariant,
                        paddingHorizontal: 16,
                        paddingTop: 4,
                        lineHeight: 18,
                    }}
                >
                    {caption}
                </Text>
            ) : null}
        </View>
    );
}

function SettingsInfoRow({
    label,
    value,
    isFirst,
    isLast,
}: {
    label: string;
    value: string;
    isFirst?: boolean;
    isLast?: boolean;
}) {
    const theme = useTheme();
    return (
        <View
            style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                paddingHorizontal: 16,
                paddingVertical: 14,
                borderTopWidth: isFirst ? 0 : 1,
                borderTopColor: theme.colors.outlineVariant,
                borderBottomWidth: 0,
                gap: 12,
            }}
        >
            <Text
                variant="bodyMedium"
                style={{
                    color: theme.colors.onSurface,
                    fontWeight: "500",
                }}
            >
                {label}
            </Text>
            <Text
                variant="bodyMedium"
                style={{
                    color: theme.colors.onSurfaceVariant,
                    flexShrink: 1,
                    textAlign: "right",
                }}
                numberOfLines={1}
            >
                {value}
            </Text>
        </View>
    );
}

function SettingsActionRow({
    label,
    icon,
    onPress,
    tone = "default",
    rightAdornment,
    isFirst,
    isLast,
}: {
    label: string;
    icon: SymbolName;
    onPress?: () => void;
    tone?: "default" | "destructive";
    rightAdornment?: React.ReactNode;
    isFirst?: boolean;
    isLast?: boolean;
}) {
    const theme = useTheme();
    const labelColor =
        tone === "destructive" ? theme.colors.error : theme.colors.primary;
    return (
        <Pressable
            onPress={onPress}
            disabled={onPress == null}
            accessibilityRole="button"
            accessibilityLabel={label}
            style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                paddingHorizontal: 16,
                paddingVertical: 14,
                borderTopWidth: isFirst ? 0 : 1,
                borderTopColor: theme.colors.outlineVariant,
                backgroundColor:
                    pressed && Platform.OS === "ios"
                        ? theme.colors.surfaceVariant
                        : "transparent",
                gap: 12,
            })}
        >
            <Symbol name={icon} size={18} color={labelColor} weight="semibold" />
            <Text
                variant="bodyMedium"
                style={{
                    color: labelColor,
                    fontWeight: "500",
                    flex: 1,
                }}
            >
                {label}
            </Text>
            {rightAdornment}
        </Pressable>
    );
}
