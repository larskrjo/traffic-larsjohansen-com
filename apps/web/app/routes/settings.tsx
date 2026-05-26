/**
 * Settings — the user-facing account-management page.
 *
 * Two sections that mirror `apps/mobile/app/trips/settings.tsx`:
 *
 *   1. **Account** — read-only name + email. Just so the user can
 *      eyeball which account they're about to nuke before they nuke it.
 *
 *   2. **Danger zone** — "Delete account" inside a tinted card. Opens
 *      a confirm dialog that requires the user to type the literal
 *      word `DELETE` (case-sensitive) before the destructive button
 *      becomes enabled.
 *
 * The web flow uses a typed-confirmation pattern (vs. the
 * double-Alert tap on mobile) because the desktop / browser context
 * supports a real text field — and typing 6 characters is a much
 * better safeguard than two "Are you sure?" clicks, which users
 * rapid-fire through. iOS doesn't get this treatment because the
 * native Alert API has no text input slot, so the mobile flow falls
 * back to the iOS-standard double-Alert pattern.
 *
 * Why this exists: Apple App Review Guideline 5.1.1(v) requires
 * every app with account creation (Sign in with Apple) to offer
 * in-app account deletion. Apple's "in app" technically means the
 * mobile binary, but parity matters — Google's Data Safety form
 * for Play Console also requires that "users can request that
 * data is deleted" and a web flow is the simplest answer.
 */
import { useState } from "react";
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Container,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    Divider,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import {
    DeleteForeverRounded,
    WarningAmberRounded,
} from "@mui/icons-material";
import { useNavigate } from "react-router";

import { AppShell } from "~/components/AppShell";
import { ProtectedRoute } from "~/components/ProtectedRoute";
import { glassCardSx } from "~/components/motion";
import { ROUTES } from "~/constants/path";
import { useSession } from "~/lib/session";

export function meta() {
    return [{ title: "Settings · time2leave" }];
}

const CONFIRM_WORD = "DELETE";

function SettingsInner() {
    const { user, deleteAccount } = useSession();
    const navigate = useNavigate();

    const [confirmOpen, setConfirmOpen] = useState(false);
    const [typed, setTyped] = useState("");
    const [deleting, setDeleting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const canDelete = typed === CONFIRM_WORD && !deleting;

    const closeDialog = () => {
        if (deleting) return;
        setConfirmOpen(false);
        setTyped("");
        setError(null);
    };

    const handleDelete = async () => {
        if (!canDelete) return;
        setDeleting(true);
        setError(null);
        try {
            await deleteAccount();
            // Local session state is already cleared by `deleteAccount`.
            // Navigate to splash so the now-anonymous user sees a clean
            // signed-out state instead of bouncing off ProtectedRoute
            // mid-render.
            navigate(ROUTES.splash, { replace: true });
        } catch (err) {
            setDeleting(false);
            setError(
                err instanceof Error
                    ? err.message
                    : "Something went wrong. Check your connection and try again.",
            );
        }
    };

    return (
        <Container maxWidth="sm" sx={{ py: { xs: 3, md: 5 } }}>
            <Stack spacing={3}>
                <Box>
                    <Typography
                        variant="h4"
                        component="h1"
                        sx={{ fontWeight: 800, letterSpacing: -0.5 }}
                    >
                        Settings
                    </Typography>
                    <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ mt: 0.5 }}
                    >
                        Account-level controls for your Time2Leave login.
                    </Typography>
                </Box>

                <Paper
                    elevation={0}
                    sx={{ ...glassCardSx, p: { xs: 2.5, md: 3 } }}
                >
                    <Stack spacing={2}>
                        <Typography
                            variant="overline"
                            color="text.secondary"
                            sx={{ letterSpacing: 0.8, fontWeight: 700 }}
                        >
                            Account
                        </Typography>
                        <Stack spacing={1.5}>
                            <Row label="Name" value={user?.name ?? "—"} />
                            <Divider />
                            <Row label="Email" value={user?.email ?? "—"} />
                        </Stack>
                    </Stack>
                </Paper>

                <Paper
                    elevation={0}
                    sx={{
                        ...glassCardSx,
                        p: { xs: 2.5, md: 3 },
                        // Pink-tinted "danger zone" card so the section
                        // reads as separate from the read-only account
                        // info above. The icon on the heading reinforces
                        // it; the body still uses standard MUI body
                        // typography so it doesn't read as a banner /
                        // error message (which would lose user trust
                        // — this isn't an *error*, it's a deliberate
                        // last-resort action).
                        borderColor: (t) => t.palette.error.light,
                        "[data-mui-color-scheme='dark'] &": {
                            borderColor: (t) => t.palette.error.dark,
                        },
                    }}
                >
                    <Stack spacing={2.5}>
                        <Stack
                            direction="row"
                            spacing={1.25}
                            alignItems="center"
                        >
                            <WarningAmberRounded
                                color="error"
                                fontSize="small"
                            />
                            <Typography
                                variant="overline"
                                sx={{
                                    letterSpacing: 0.8,
                                    fontWeight: 700,
                                    color: "error.main",
                                }}
                            >
                                Danger zone
                            </Typography>
                        </Stack>
                        <Stack spacing={1}>
                            <Typography variant="subtitle1" fontWeight={700}>
                                Delete account
                            </Typography>
                            <Typography
                                variant="body2"
                                color="text.secondary"
                                sx={{ lineHeight: 1.55 }}
                            >
                                Permanently delete your account, every
                                trip you&apos;ve saved, and the full
                                drive-time history we&apos;ve collected
                                for them. This action can&apos;t be
                                undone.
                            </Typography>
                        </Stack>
                        <Box>
                            <Button
                                variant="outlined"
                                color="error"
                                startIcon={<DeleteForeverRounded />}
                                onClick={() => setConfirmOpen(true)}
                            >
                                Delete account
                            </Button>
                        </Box>
                    </Stack>
                </Paper>
            </Stack>

            <Dialog
                open={confirmOpen}
                onClose={closeDialog}
                fullWidth
                maxWidth="xs"
                aria-labelledby="delete-account-title"
            >
                <DialogTitle
                    id="delete-account-title"
                    sx={{ display: "flex", alignItems: "center", gap: 1 }}
                >
                    <WarningAmberRounded color="error" />
                    Delete account?
                </DialogTitle>
                <DialogContent>
                    <DialogContentText sx={{ mb: 2 }}>
                        This will permanently delete your account, every
                        saved trip, and every drive-time sample tied to
                        it. Your invite remains on the operator&apos;s
                        allowlist — if you change your mind later, you
                        can sign in again to create a fresh account,
                        but the previous data will not come back.
                    </DialogContentText>
                    <DialogContentText sx={{ mb: 1.5 }}>
                        Type <strong>{CONFIRM_WORD}</strong> below to
                        confirm.
                    </DialogContentText>
                    <TextField
                        autoFocus
                        fullWidth
                        size="small"
                        value={typed}
                        onChange={(event) => setTyped(event.target.value)}
                        placeholder={CONFIRM_WORD}
                        disabled={deleting}
                        // Disable browser-level autofill / autocorrect on
                        // this field — it's a one-shot literal-string
                        // confirmation, not a real input the user wants
                        // remembered or auto-suggested.
                        inputProps={{
                            "aria-label": "Type DELETE to confirm",
                            autoCapitalize: "characters",
                            autoCorrect: "off",
                            spellCheck: false,
                        }}
                    />
                    {error ? (
                        <Alert severity="error" sx={{ mt: 2 }}>
                            {error}
                        </Alert>
                    ) : null}
                </DialogContent>
                <DialogActions sx={{ px: 3, pb: 2 }}>
                    <Button onClick={closeDialog} disabled={deleting}>
                        Cancel
                    </Button>
                    <Button
                        onClick={handleDelete}
                        color="error"
                        variant="contained"
                        disabled={!canDelete}
                        startIcon={
                            deleting ? (
                                <CircularProgress
                                    size={16}
                                    color="inherit"
                                />
                            ) : (
                                <DeleteForeverRounded />
                            )
                        }
                    >
                        {deleting ? "Deleting…" : "Delete account"}
                    </Button>
                </DialogActions>
            </Dialog>
        </Container>
    );
}

function Row({ label, value }: { label: string; value: string }) {
    return (
        <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="baseline"
            spacing={2}
        >
            <Typography variant="body2" color="text.secondary">
                {label}
            </Typography>
            <Typography
                variant="body2"
                sx={{
                    fontWeight: 500,
                    textAlign: "right",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                }}
            >
                {value}
            </Typography>
        </Stack>
    );
}

export default function SettingsPage() {
    return (
        <ProtectedRoute>
            <AppShell>
                <SettingsInner />
            </AppShell>
        </ProtectedRoute>
    );
}
