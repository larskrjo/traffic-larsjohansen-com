/**
 * Public Support page.
 *
 * Required by Apple — App Store Connect's `Support URL` field is
 * mandatory and gets clicked during App Review on a clean browser
 * session, so this page must:
 *
 *   1. Resolve without authentication (no `ProtectedRoute`).
 *   2. Render something that visibly reads as "support" — name of
 *      the app, what it does, and a clear way to get in touch.
 *   3. Link to the privacy policy and to the in-app account-deletion
 *      flow, both of which the reviewer is also instructed to test.
 *
 * The page intentionally stays short and scannable. A long FAQ would
 * be noise — the App Store reviewer needs to confirm the URL works
 * and lists a way to reach a human; everything else can live in the
 * app itself.
 */
import {
    Box,
    Button,
    Container,
    Link as MuiLink,
    Paper,
    Stack,
    Typography,
} from "@mui/material";
import {
    DeleteOutlineRounded,
    LockOutlined,
    MailOutlineRounded,
    SettingsRounded,
} from "@mui/icons-material";
import { Link as RouterLink } from "react-router";

import { AppShell } from "~/components/AppShell";
import { glassCardSx } from "~/components/motion";
import { ROUTES } from "~/constants/path";

// Single source of truth for the support contact. Update here if /
// when a dedicated `support@time2leave.com` address is set up.
const SUPPORT_EMAIL = "larskrjo@gmail.com";

export function meta() {
    return [
        { title: "Support · time2leave" },
        {
            name: "description",
            content:
                "Get help, contact the team, manage or delete your time2leave account.",
        },
    ];
}

function SupportInner() {
    const mailto =
        `mailto:${SUPPORT_EMAIL}` +
        `?subject=${encodeURIComponent("Time2Leave support")}`;

    return (
        <Container maxWidth="sm" sx={{ py: { xs: 3, md: 5 } }}>
            <Stack spacing={3}>
                <Box>
                    <Typography
                        variant="h4"
                        component="h1"
                        sx={{ fontWeight: 800, letterSpacing: -0.5 }}
                    >
                        Support
                    </Typography>
                    <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ mt: 0.5 }}
                    >
                        Time2Leave shows a 7-day heatmap of how long your
                        commute will actually take — every 15 minutes,
                        both directions. Hit any of the options below if
                        something isn&apos;t working or you need to
                        change your account.
                    </Typography>
                </Box>

                <Paper
                    elevation={0}
                    sx={{ ...glassCardSx, p: { xs: 2.5, md: 3 } }}
                >
                    <Stack spacing={2}>
                        <SectionLabel>Get in touch</SectionLabel>
                        <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ lineHeight: 1.55 }}
                        >
                            Bug report, feature request, or anything else
                            — email us and we&apos;ll get back to you.
                            Please include your iOS version and a short
                            description of what you were doing when the
                            issue happened; that&apos;s usually enough to
                            reproduce.
                        </Typography>
                        <Box>
                            <Button
                                component={MuiLink}
                                href={mailto}
                                variant="contained"
                                startIcon={<MailOutlineRounded />}
                            >
                                Email support
                            </Button>
                        </Box>
                        <Typography
                            variant="caption"
                            color="text.secondary"
                        >
                            Or copy:{" "}
                            <MuiLink
                                href={mailto}
                                sx={{ fontFamily: "monospace" }}
                            >
                                {SUPPORT_EMAIL}
                            </MuiLink>
                        </Typography>
                    </Stack>
                </Paper>

                <Paper
                    elevation={0}
                    sx={{ ...glassCardSx, p: { xs: 2.5, md: 3 } }}
                >
                    <Stack spacing={2}>
                        <SectionLabel>Manage your account</SectionLabel>
                        <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ lineHeight: 1.55 }}
                        >
                            Sign in to view your saved trips, change
                            your details, or permanently delete your
                            account. Deleting your account wipes every
                            saved trip and every drive-time sample
                            we&apos;ve collected for you.
                        </Typography>
                        <Stack
                            direction={{ xs: "column", sm: "row" }}
                            spacing={1.5}
                        >
                            <Button
                                component={RouterLink}
                                to={ROUTES.settings}
                                variant="outlined"
                                startIcon={<SettingsRounded />}
                            >
                                Open settings
                            </Button>
                            <Button
                                component={RouterLink}
                                to={ROUTES.settings}
                                variant="text"
                                color="error"
                                startIcon={<DeleteOutlineRounded />}
                            >
                                Delete account
                            </Button>
                        </Stack>
                    </Stack>
                </Paper>

                <Paper
                    elevation={0}
                    sx={{ ...glassCardSx, p: { xs: 2.5, md: 3 } }}
                >
                    <Stack spacing={2}>
                        <SectionLabel>Privacy &amp; data</SectionLabel>
                        <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ lineHeight: 1.55 }}
                        >
                            Time2Leave collects only the email tied to
                            your sign-in and the trip addresses you save.
                            No location tracking, no third-party
                            analytics, no ad networks. The full policy
                            spells out exactly what we collect and why.
                        </Typography>
                        <Box>
                            <Button
                                component={RouterLink}
                                to={ROUTES.privacy}
                                variant="outlined"
                                startIcon={<LockOutlined />}
                            >
                                Read the privacy policy
                            </Button>
                        </Box>
                    </Stack>
                </Paper>
            </Stack>
        </Container>
    );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
    return (
        <Typography
            variant="overline"
            color="text.secondary"
            sx={{ letterSpacing: 0.8, fontWeight: 700 }}
        >
            {children}
        </Typography>
    );
}

export default function SupportPage() {
    return (
        <AppShell>
            <SupportInner />
        </AppShell>
    );
}
