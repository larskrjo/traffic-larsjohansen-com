/**
 * Animated landing page for anonymous visitors.
 *
 * Three sections: hero with sign-in, how-it-works (3 steps), and a
 * demo heatmap that visualizes what signed-in users get. Authenticated
 * visitors are redirected straight to /trips so this page is only
 * ever seen by newcomers.
 */
import { useRef, type ReactNode } from "react";
import { Link as RouterLink, Navigate, useSearchParams } from "react-router";
import {
    Avatar,
    Box,
    Button,
    Card,
    CardContent,
    Container,
    Stack,
    Typography,
    useTheme,
} from "@mui/material";
import {
    AccessTimeRounded,
    LoginRounded,
    PlaceRounded,
    TuneRounded,
} from "@mui/icons-material";
import { motion, useAnimation, useReducedMotion } from "framer-motion";

import { DemoHeatmap } from "~/components/DemoHeatmap";
import { DevLoginButton } from "~/components/DevLoginButton";
import { GoogleSignInButton } from "~/components/GoogleSignInButton";
import { Wordmark } from "~/components/Wordmark";
import { glassCardSx, primaryCtaSx } from "~/components/motion";
import { ROUTES } from "~/constants/path";
import { useSession } from "~/lib/session";
import Loading from "~/components/Loading";

export function meta() {
    return [
        { title: "time2leave — know exactly when" },
        {
            name: "description",
            content:
                "Save any A→B trip and time2leave tells you exactly when — down to the 15-minute interval, every day of the week.",
        },
    ];
}

type Step = {
    icon: ReactNode;
    title: string;
    body: string;
};

const STEPS: Step[] = [
    {
        icon: <PlaceRounded />,
        title: "Add your addresses",
        body: "Drop in the two endpoints of any regular drive — home to work, school pickup, airport runs, whatever you repeat.",
    },
    {
        icon: <TuneRounded />,
        title: "We sample 15-minute windows, 6am-9pm, both ways",
        body: "Every Monday morning we refresh the week ahead using the Google Routes Matrix API so your plan always reflects live traffic patterns.",
    },
    {
        icon: <AccessTimeRounded />,
        title: "Leave at the right time",
        body: "A color-coded heatmap shows exactly how long the drive will take at each departure slot — spot the gentle dip before rush hour and go.",
    },
];

function FadeIn({
    children,
    delay = 0,
}: {
    children: ReactNode;
    delay?: number;
}) {
    const reduce = useReducedMotion();
    return (
        <motion.div
            initial={reduce ? { opacity: 1 } : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay, ease: "easeOut" }}
        >
            {children}
        </motion.div>
    );
}

function AnimatedBackdrop() {
    const reduce = useReducedMotion();
    return (
        <Box
            aria-hidden
            sx={{
                position: "absolute",
                inset: 0,
                overflow: "hidden",
                zIndex: -1,
            }}
        >
            {[0, 1, 2].map((i) => (
                <motion.div
                    key={i}
                    initial={{ opacity: 0.0 }}
                    animate={
                        reduce
                            ? { opacity: 0.35 }
                            : {
                                  opacity: [0.3, 0.55, 0.3],
                                  x: [0, 40, 0],
                                  y: [0, -20, 0],
                              }
                    }
                    transition={{
                        repeat: Infinity,
                        duration: 14 + i * 3,
                        ease: "easeInOut",
                    }}
                    style={{
                        position: "absolute",
                        top: `${10 + i * 20}%`,
                        left: `${[-10, 55, 20][i]}%`,
                        width: 380,
                        height: 380,
                        borderRadius: "50%",
                        background: [
                            "radial-gradient(circle at 30% 30%, #c7d8ff, transparent 60%)",
                            "radial-gradient(circle at 70% 40%, #ffe5c7, transparent 60%)",
                            "radial-gradient(circle at 40% 70%, #d2f5e7, transparent 60%)",
                        ][i],
                        filter: "blur(40px)",
                    }}
                />
            ))}
        </Box>
    );
}

export default function SplashPage() {
    const theme = useTheme();
    const { status } = useSession();
    const [params] = useSearchParams();
    const next = params.get("next") ?? ROUTES.trips;
    const reduce = useReducedMotion();

    // The CTA card lives in the hero, but the user might scroll past it
    // to read "How it works" before deciding to sign in. The top-right
    // "Sign in" button (always visible) scrolls back to the CTA *and*
    // briefly pulses it so the eye lands in the right place.
    const ctaRef = useRef<HTMLDivElement | null>(null);
    const pulseControls = useAnimation();

    const scrollToSignIn = () => {
        ctaRef.current?.scrollIntoView({
            behavior: reduce ? "auto" : "smooth",
            block: "center",
        });
        if (reduce) return;
        void pulseControls.start({
            boxShadow: [
                "0 0 0 0 rgba(30,64,175,0)",
                "0 0 0 12px rgba(30,64,175,0.28)",
                "0 0 0 0 rgba(30,64,175,0)",
            ],
            transition: { duration: 1.4, ease: "easeOut" },
        });
    };

    if (status === "loading") return <Loading />;
    if (status === "authenticated") return <Navigate to={next} replace />;

    return (
        <Box
            component="main"
            sx={{
                position: "relative",
                minHeight: "100vh",
                overflow: "hidden",
                color: "text.primary",
                background:
                    "linear-gradient(180deg, #f5f8ff 0%, #ffffff 60%, #fff8f0 100%)",
                "[data-mui-color-scheme='dark'] &": {
                    background:
                        "linear-gradient(180deg, #0b1020 0%, #121a33 60%, #1a1528 100%)",
                },
            }}
        >
            <AnimatedBackdrop />

            {/* Brand anchor on the left, persistent "Sign in" CTA on
                the right. The button works two ways: as a redundant
                sign-in entry point (so users who scroll past the hero
                still see how to get in) and as a smooth-scroll back to
                the CTA card with a brief glow pulse to guide the eye.

                No theme toggle here by design: the signed-out
                experience always mirrors local time (dark at night,
                light during the day). The full three-state control
                appears after sign-in. */}
            <Container maxWidth="lg" sx={{ pt: { xs: 3, md: 4 }, pb: 0 }}>
                <Stack
                    direction="row"
                    alignItems="center"
                    justifyContent="space-between"
                >
                    <Wordmark size="md" />
                    <Button
                        variant="contained"
                        size="medium"
                        startIcon={<LoginRounded />}
                        onClick={scrollToSignIn}
                        sx={{
                            ...primaryCtaSx,
                            // Slightly trimmer than the standard primary
                            // CTA so it doesn't crowd the wordmark on
                            // narrow viewports.
                            px: { xs: 2, sm: 2.5 },
                            py: { xs: 0.75, sm: 1 },
                            fontSize: { xs: 13, sm: 14 },
                        }}
                    >
                        Sign in
                    </Button>
                </Stack>
            </Container>

            {/* Hero */}
            <Container maxWidth="lg" sx={{ pt: { xs: 4, md: 8 }, pb: 8 }}>
                <Stack
                    direction={{ xs: "column", md: "row" }}
                    spacing={{ xs: 6, md: 8 }}
                    alignItems="center"
                >
                    <Stack spacing={3} sx={{ flex: 1, minWidth: 0 }}>
                        <FadeIn>
                            <Typography
                                variant="overline"
                                sx={{
                                    color: theme.palette.primary.main,
                                    fontWeight: 700,
                                    letterSpacing: 2,
                                }}
                            >
                                Know when to leave
                            </Typography>
                        </FadeIn>
                        <FadeIn delay={0.1}>
                            <Typography
                                variant="h2"
                                sx={{
                                    fontWeight: 800,
                                    lineHeight: 1.05,
                                    fontSize: { xs: 40, sm: 52, md: 64 },
                                }}
                            >
                                Stop{" "}
                                <Box
                                    component="span"
                                    sx={{
                                        background:
                                            "linear-gradient(135deg, #1e40af 0%, #ef6c00 100%)",
                                        WebkitBackgroundClip: "text",
                                        WebkitTextFillColor: "transparent",
                                    }}
                                >
                                    guessing
                                </Box>{" "}
                                when to leave.
                            </Typography>
                        </FadeIn>
                        <FadeIn delay={0.2}>
                            <Typography
                                variant="h6"
                                color="text.secondary"
                                sx={{ maxWidth: 520, fontWeight: 400 }}
                            >
                                Save a trip between any two addresses. We build
                                a heatmap of real drive times in 15-minute
                                intervals across the whole week — both
                                directions, weekends included.
                            </Typography>
                        </FadeIn>
                        <FadeIn delay={0.35}>
                            {/* Frame the sign-in button so it actually
                                reads as the page's primary action.
                                Without this the official GSI pill blends
                                into the background and visitors miss it.
                                The motion.div wraps the card so the
                                top-right "Sign in" button can pulse this
                                element when the user clicks it. */}
                            {/* `display: block` + `width: 100%, maxWidth: 420`
                                so the wrapper hugs the card on both axes:
                                shrinks below 420 on narrow viewports
                                (otherwise a fixed-width GSI iframe inside
                                would push it past the column edge), and
                                caps at 420 on wide viewports (otherwise
                                the wrapper would stretch to the full
                                column width and the pulse animation's
                                box-shadow would draw a phantom frame
                                around empty space to the right of the
                                card). */}
                            <motion.div
                                ref={ctaRef}
                                id="sign-in"
                                animate={pulseControls}
                                style={{
                                    display: "block",
                                    width: "100%",
                                    maxWidth: 420,
                                    borderRadius: 16,
                                    scrollMarginTop: 96,
                                }}
                            >
                                <Box
                                    sx={{
                                        ...glassCardSx,
                                        width: "100%",
                                        maxWidth: 420,
                                        p: { xs: 2, sm: 2.5, md: 3 },
                                        // Defensive guard: if anything
                                        // inside ever overflows (a fixed-
                                        // width iframe, a long URL, etc.)
                                        // contain it here instead of
                                        // letting it bleed into the
                                        // page's horizontal scroll.
                                        overflow: "hidden",
                                    }}
                                >
                                    <Typography
                                        variant="overline"
                                        sx={{
                                            color: theme.palette.primary.main,
                                            fontWeight: 700,
                                            letterSpacing: 1.5,
                                            display: "block",
                                            mb: 0.5,
                                        }}
                                    >
                                        Get started
                                    </Typography>
                                    <Typography
                                        variant="h6"
                                        sx={{
                                            fontWeight: 700,
                                            mb: 1.5,
                                            lineHeight: 1.3,
                                        }}
                                    >
                                        Sign in to save your first trip
                                    </Typography>
                                    <GoogleSignInButton />
                                    <Typography
                                        variant="caption"
                                        color="text.secondary"
                                        sx={{
                                            display: "block",
                                            mt: 1.5,
                                            lineHeight: 1.5,
                                        }}
                                    >
                                        Invite-only today — your email needs
                                        to be on the allowlist. Ask the
                                        owner to add you.
                                    </Typography>
                                    <DevLoginButton />
                                </Box>
                            </motion.div>
                        </FadeIn>
                    </Stack>

                    {/* The flex sizing has to live on an element that is
                        a direct child of the hero Stack — FadeIn wraps
                        its children in a plain motion.div with no flex
                        styles, so putting `flex: 1` inside FadeIn does
                        nothing. `minWidth: 0` lets this column actually
                        shrink on narrow viewports instead of forcing
                        the whole hero wider than the Container and
                        triggering the left/right clipping we had. */}
                    <Box sx={{ flex: 1, minWidth: 0, width: "100%" }}>
                        <FadeIn delay={0.3}>
                            <DemoHeatmap />
                            <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{
                                    display: "block",
                                    textAlign: "center",
                                    mt: 1.5,
                                }}
                            >
                                A real heatmap: 7 days × 15-minute slots, both
                                directions. Green = fast, red = sit in traffic.
                            </Typography>
                        </FadeIn>
                    </Box>
                </Stack>
            </Container>

            {/* How it works */}
            <Container maxWidth="lg" sx={{ py: { xs: 6, md: 10 } }}>
                <FadeIn>
                    <Typography
                        variant="h4"
                        sx={{
                            fontWeight: 700,
                            textAlign: "center",
                            mb: { xs: 4, md: 6 },
                        }}
                    >
                        How it works
                    </Typography>
                </FadeIn>
                <Stack
                    direction={{ xs: "column", md: "row" }}
                    spacing={{ xs: 2.5, md: 4 }}
                >
                    {STEPS.map((step, idx) => (
                        <FadeIn key={step.title} delay={0.15 * idx}>
                            <Card
                                variant="outlined"
                                sx={{
                                    height: "100%",
                                    ...glassCardSx,
                                }}
                            >
                                <CardContent sx={{ p: { xs: 3, md: 4 } }}>
                                    <Avatar
                                        sx={{
                                            bgcolor: "primary.main",
                                            color: "primary.contrastText",
                                            width: 48,
                                            height: 48,
                                            mb: 2,
                                        }}
                                    >
                                        {step.icon}
                                    </Avatar>
                                    <Typography
                                        variant="overline"
                                        color="text.secondary"
                                    >
                                        Step {idx + 1}
                                    </Typography>
                                    <Typography
                                        variant="h6"
                                        sx={{ fontWeight: 700, mt: 0.5, mb: 1 }}
                                    >
                                        {step.title}
                                    </Typography>
                                    <Typography
                                        variant="body2"
                                        color="text.secondary"
                                    >
                                        {step.body}
                                    </Typography>
                                </CardContent>
                            </Card>
                        </FadeIn>
                    ))}
                </Stack>
            </Container>

            {/* Bottom-of-page CTA: catches users who read all the way
                through "How it works" and decide they want in. Without
                this the only sign-in entry point is the (now scrolled-
                away) hero card, which is a usability cliff. */}
            <Container maxWidth="lg" sx={{ pb: 6 }}>
                <Box
                    sx={{
                        textAlign: "center",
                        py: { xs: 4, md: 6 },
                        borderTop: (t) => `1px solid ${t.palette.divider}`,
                    }}
                >
                    <Typography
                        variant="h5"
                        sx={{ fontWeight: 700, mb: 2 }}
                    >
                        Ready to stop guessing?
                    </Typography>
                    <Button
                        variant="contained"
                        size="large"
                        startIcon={<LoginRounded />}
                        onClick={scrollToSignIn}
                        sx={primaryCtaSx}
                    >
                        Sign in to get started
                    </Button>
                </Box>
            </Container>

            {/* Footer: legal + contact discoverability. The Privacy
                Policy and Support URLs are required by App Store
                Connect; surfacing them here too means an anonymous
                visitor (and Apple Review) can always find them
                without typing the path manually. The links are
                lightweight and intentionally separated from the
                marketing CTAs above. */}
            <Container maxWidth="lg" sx={{ pb: { xs: 4, md: 6 } }}>
                <Stack
                    direction={{ xs: "column", sm: "row" }}
                    spacing={{ xs: 1.5, sm: 3 }}
                    alignItems="center"
                    justifyContent="center"
                    sx={{
                        pt: { xs: 3, md: 4 },
                        borderTop: (t) => `1px solid ${t.palette.divider}`,
                    }}
                >
                    <Typography variant="caption" color="text.secondary">
                        © {new Date().getFullYear()} Time2Leave
                    </Typography>
                    <Button
                        component={RouterLink}
                        to={ROUTES.privacy}
                        size="small"
                        sx={{ textTransform: "none", color: "text.secondary" }}
                    >
                        Privacy
                    </Button>
                    <Button
                        component={RouterLink}
                        to={ROUTES.support}
                        size="small"
                        sx={{ textTransform: "none", color: "text.secondary" }}
                    >
                        Support
                    </Button>
                </Stack>
            </Container>
        </Box>
    );
}
