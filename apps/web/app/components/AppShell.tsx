/**
 * Top-level navigation shell for authenticated pages.
 *
 * Shows the product name (links back to /trips), and an avatar button
 * that opens a menu with "Sign out". Pages render inside a MUI
 * <Container>. Intentionally small — the look/feel polish lives in the
 * per-page components and the theme.
 */
import { useState, type ReactNode } from "react";
import {
    AppBar,
    Avatar,
    Box,
    Container,
    Divider,
    IconButton,
    ListItemIcon,
    ListItemText,
    Menu,
    MenuItem,
    Toolbar,
    Typography,
} from "@mui/material";
import {
    LockPersonRounded,
    LogoutRounded,
    SettingsRounded,
} from "@mui/icons-material";
import { Link as RouterLink, useNavigate } from "react-router";

import { ColorModeToggle } from "~/components/ColorModeToggle";
import { Wordmark } from "~/components/Wordmark";
import { ROUTES } from "~/constants/path";
import { useSession } from "~/lib/session";
import { PageBackdrop } from "~/components/motion";

function initialsFor(name: string | null, email: string): string {
    if (name && name.trim().length > 0) {
        const parts = name.trim().split(/\s+/);
        const first = parts[0][0];
        const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
        return (first + last).toUpperCase();
    }
    return email.slice(0, 2).toUpperCase();
}

export function AppShell({ children }: { children: ReactNode }) {
    const { user, logout } = useSession();
    const [anchor, setAnchor] = useState<HTMLElement | null>(null);
    const navigate = useNavigate();

    const handleLogout = async () => {
        setAnchor(null);
        await logout();
        navigate(ROUTES.splash, { replace: true });
    };

    return (
        <PageBackdrop>
            <Box
                sx={{
                    display: "flex",
                    flexDirection: "column",
                    minHeight: "100vh",
                }}
            >
                <AppBar
                    position="sticky"
                    elevation={0}
                    color="transparent"
                    sx={{
                        backdropFilter: "saturate(180%) blur(14px)",
                        WebkitBackdropFilter: "saturate(180%) blur(14px)",
                        backgroundColor: "rgba(255,255,255,0.6)",
                        borderBottom: "1px solid rgba(30,64,175,0.08)",
                        "[data-mui-color-scheme='dark'] &": {
                            backgroundColor: "rgba(11,16,32,0.65)",
                            borderBottom: "1px solid rgba(255,255,255,0.06)",
                        },
                    }}
                >
                    <Container maxWidth="lg">
                        <Toolbar disableGutters sx={{ gap: 2 }}>
                            <Box
                                component={RouterLink}
                                to={ROUTES.trips}
                                sx={{
                                    textDecoration: "none",
                                    display: "flex",
                                    alignItems: "baseline",
                                    gap: 1,
                                    flexGrow: 1,
                                }}
                            >
                                <Wordmark size="md" />
                            </Box>
                            <ColorModeToggle />
                            {user && (
                                <>
                                    <IconButton
                                        onClick={(e) => setAnchor(e.currentTarget)}
                                        size="small"
                                        aria-label="account menu"
                                        sx={{
                                            p: 0.5,
                                            transition: "transform 160ms ease",
                                            "&:hover": {
                                                transform: "scale(1.05)",
                                            },
                                        }}
                                    >
                                        {user.picture_url ? (
                                            <Avatar
                                                src={user.picture_url}
                                                alt={user.name ?? user.email}
                                                sx={{
                                                    width: 36,
                                                    height: 36,
                                                    border: "2px solid rgba(30,64,175,0.2)",
                                                }}
                                            />
                                        ) : (
                                            <Avatar
                                                sx={{
                                                    width: 36,
                                                    height: 36,
                                                    background:
                                                        "linear-gradient(135deg, #1e40af, #ef6c00)",
                                                    color: "white",
                                                    fontWeight: 700,
                                                    fontSize: 14,
                                                }}
                                            >
                                                {initialsFor(user.name, user.email)}
                                            </Avatar>
                                        )}
                                    </IconButton>
                                    <Menu
                                        anchorEl={anchor}
                                        open={Boolean(anchor)}
                                        onClose={() => setAnchor(null)}
                                        anchorOrigin={{
                                            vertical: "bottom",
                                            horizontal: "right",
                                        }}
                                        transformOrigin={{
                                            vertical: "top",
                                            horizontal: "right",
                                        }}
                                        slotProps={{
                                            paper: {
                                                elevation: 0,
                                                sx: {
                                                    mt: 1,
                                                    borderRadius: 3,
                                                    minWidth: 220,
                                                    border: "1px solid rgba(30,64,175,0.12)",
                                                    backdropFilter: "blur(10px)",
                                                    backgroundColor: "rgba(255,255,255,0.88)",
                                                    boxShadow:
                                                        "0 12px 32px -16px rgba(0,0,0,0.35)",
                                                    "[data-mui-color-scheme='dark'] &": {
                                                        border: "1px solid rgba(255,255,255,0.08)",
                                                        backgroundColor:
                                                            "rgba(18,26,51,0.92)",
                                                    },
                                                },
                                            },
                                        }}
                                    >
                                        <MenuItem disabled sx={{ opacity: 1 }}>
                                            <Box>
                                                <Typography
                                                    variant="subtitle2"
                                                    sx={{ fontWeight: 700 }}
                                                >
                                                    {user.name ?? user.email}
                                                </Typography>
                                                <Typography
                                                    variant="caption"
                                                    color="text.secondary"
                                                >
                                                    {user.email}
                                                </Typography>
                                            </Box>
                                        </MenuItem>
                                        {user.is_admin && (
                                            <Box>
                                                <Divider sx={{ my: 0.5 }} />
                                                <MenuItem
                                                    component={RouterLink}
                                                    to={ROUTES.adminAllowlist}
                                                    onClick={() =>
                                                        setAnchor(null)
                                                    }
                                                >
                                                    <ListItemIcon>
                                                        <LockPersonRounded fontSize="small" />
                                                    </ListItemIcon>
                                                    <ListItemText>
                                                        Manage allowlist
                                                    </ListItemText>
                                                </MenuItem>
                                            </Box>
                                        )}
                                        <Divider sx={{ my: 0.5 }} />
                                        <MenuItem
                                            component={RouterLink}
                                            to={ROUTES.settings}
                                            onClick={() => setAnchor(null)}
                                        >
                                            <ListItemIcon>
                                                <SettingsRounded fontSize="small" />
                                            </ListItemIcon>
                                            <ListItemText>
                                                Settings
                                            </ListItemText>
                                        </MenuItem>
                                        <MenuItem onClick={handleLogout}>
                                            <ListItemIcon>
                                                <LogoutRounded fontSize="small" />
                                            </ListItemIcon>
                                            <ListItemText>
                                                Sign out
                                            </ListItemText>
                                        </MenuItem>
                                    </Menu>
                                </>
                            )}
                        </Toolbar>
                    </Container>
                </AppBar>
                <Container
                    component="main"
                    maxWidth="lg"
                    sx={{ py: { xs: 3, md: 5 }, flexGrow: 1 }}
                >
                    {children}
                </Container>
            </Box>
        </PageBackdrop>
    );
}
