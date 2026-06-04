/**
 * Public Privacy Policy.
 *
 * Required by Apple — App Store Connect's `Privacy Policy URL` field
 * is mandatory for any app that collects user data (which Time2Leave
 * does, via Sign in with Apple / Google) and gets hard-rejected on
 * submission if it doesn't resolve to a valid policy. Apple Review
 * will click this URL during review.
 *
 * The policy is intentionally specific about what we actually do —
 * boilerplate templates ("we may share your data with our partners")
 * trigger a tougher reviewer questionnaire than a tight, accurate
 * description does. Keep this in sync with `STORE_RELEASE.md` §3
 * (Apple App Privacy disclosures) and `backend/app/services/users.py`
 * (the actual user-table schema).
 */
import {
    Box,
    Container,
    Link as MuiLink,
    Paper,
    Stack,
    Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router";

import { AppShell } from "~/components/AppShell";
import { glassCardSx } from "~/components/motion";
import { ROUTES } from "~/constants/path";

// Single source of truth for the privacy contact email. Same address
// the Support page uses.
const PRIVACY_EMAIL = "larskrjo@gmail.com";

// Bump this when the policy changes. App Store Review uses the
// effective date to verify a policy actually exists (i.e. isn't a
// placeholder page).
const EFFECTIVE_DATE = "June 4, 2026";

export function meta() {
    return [
        { title: "Privacy Policy · time2leave" },
        {
            name: "description",
            content:
                "What time2leave collects, why, where it's stored, and how to delete it.",
        },
    ];
}

function PrivacyInner() {
    return (
        <Container maxWidth="md" sx={{ py: { xs: 3, md: 5 } }}>
            <Stack spacing={3}>
                <Box>
                    <Typography
                        variant="h4"
                        component="h1"
                        sx={{ fontWeight: 800, letterSpacing: -0.5 }}
                    >
                        Privacy Policy
                    </Typography>
                    <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ mt: 0.5 }}
                    >
                        Effective {EFFECTIVE_DATE}
                    </Typography>
                </Box>

                <Paper
                    elevation={0}
                    sx={{ ...glassCardSx, p: { xs: 2.5, md: 3 } }}
                >
                    <Stack spacing={2}>
                        <Body>
                            Time2Leave (&ldquo;we&rdquo;,
                            &ldquo;us&rdquo;) provides a per-trip
                            commute-time heatmap on iOS and at{" "}
                            <MuiLink href="https://time2leave.com">
                                time2leave.com
                            </MuiLink>
                            . This policy explains exactly what data we
                            collect, why, who else sees it, and how to
                            delete it.
                        </Body>
                    </Stack>
                </Paper>

                <Section title="1. What we collect">
                    <Body>
                        From your <strong>sign-in</strong> (Apple or
                        Google):
                    </Body>
                    <Bullets
                        items={[
                            "Your email address — used to identify your account across sessions and devices.",
                            "Your name and profile picture URL, if your sign-in provider shares them — used to display your account in the app.",
                            "An opaque identifier issued by Apple or Google so we can recognise you on next sign-in without re-asking for permissions.",
                        ]}
                    />
                    <Body>
                        From your <strong>use of the app</strong>:
                    </Body>
                    <Bullets
                        items={[
                            "The two addresses (origin and destination) of every trip you save.",
                            "The drive-time samples we compute for those trips — a 7-day, 15-minute-resolution table of expected durations.",
                            "Standard server logs (HTTP request paths, IP address, user-agent) kept only as long as needed for operational debugging.",
                        ]}
                    />
                    <Body>
                        We do <strong>not</strong> collect your real-time
                        location, your contacts, your photos, your
                        calendar, your microphone, or any other on-device
                        data. The iOS app asks for zero device
                        permissions.
                    </Body>
                </Section>

                <Section title="2. Why we collect it">
                    <Bullets
                        items={[
                            "Email + opaque identifier: to authenticate you and tie your saved trips to your account.",
                            "Name + picture: to show in the app so you know which account you're signed in to.",
                            "Trip addresses: to query the Google Maps Routes API and compute the drive-time heatmap that is the whole product.",
                            "Drive-time samples: cached on our backend so opening the app is instant and you can see the same heatmap across devices.",
                            "Server logs: to investigate errors and abuse. Not used for any other purpose.",
                        ]}
                    />
                </Section>

                <Section title="3. Who we share it with">
                    <Body>
                        We do <strong>not</strong> sell your data, and we
                        do <strong>not</strong> share it with
                        advertising networks, data brokers, or
                        third-party analytics services. The only
                        third parties that receive any of your data are
                        the providers we technically need to make the
                        app work:
                    </Body>
                    <Bullets
                        items={[
                            "Google Maps Platform — receives the addresses of trips you save so it can compute drive times. Google sees the trip addresses; it does not see your email, name, or account identifier. Google's terms: policies.google.com/privacy.",
                            "Apple Sign-In and Google Sign-In — handle the actual sign-in flow per their standard protocols. You authenticate with them directly; they tell us only what's needed to identify you (your email and the opaque identifier).",
                            "Amazon Web Services (AWS) — hosts our backend in the US-West-2 region. AWS does not access the data we store; it provides the storage and compute on which we run.",
                        ]}
                    />
                    <Body>
                        We <strong>never</strong> ship any third-party
                        SDK that does cross-app tracking. No Facebook
                        Pixel, no AppsFlyer, no Mixpanel, no advertising
                        identifiers — we don&apos;t even read the iOS
                        Advertising ID (IDFA).
                    </Body>
                </Section>

                <Section title="4. Where it's stored">
                    <Body>
                        Your account row, saved trips, and computed
                        drive-time samples are stored in a MySQL
                        database running on AWS EC2 in the US-West-2
                        region. Data in transit between your device and
                        our backend is encrypted with TLS. Data at rest
                        is retained for as long as your account exists.
                    </Body>
                </Section>

                <Section title="5. Your rights">
                    <Body>
                        You can permanently delete your account, every
                        saved trip, and every drive-time sample we
                        have for you at any time:
                    </Body>
                    <Bullets
                        items={[
                            "In the iOS app: tap the gear icon on the Trips screen → Danger zone → Delete account.",
                            "On the web: sign in, open Settings → Danger zone → Delete account, and type DELETE to confirm.",
                            "By email: write to " + PRIVACY_EMAIL + " from the email address tied to your account and we will action the deletion within 30 days.",
                        ]}
                    />
                    <Body>
                        Deletion is immediate and unrecoverable. We do
                        not keep a soft-deleted copy. If you change
                        your mind, you can sign in again with the same
                        Apple or Google account to start fresh — but
                        the previous trips and samples will not come
                        back.
                    </Body>
                    <Body>
                        You can also reach{" "}
                        <MuiLink
                            component={RouterLink}
                            to={ROUTES.support}
                        >
                            Support
                        </MuiLink>{" "}
                        for any other data-access or correction request.
                    </Body>
                </Section>

                <Section title="6. Children">
                    <Body>
                        Time2Leave is not directed at children under 13,
                        and we do not knowingly collect data from anyone
                        under that age. If you believe a child has
                        signed up, email {PRIVACY_EMAIL} and we will
                        delete the account.
                    </Body>
                </Section>

                <Section title="7. Changes to this policy">
                    <Body>
                        If we change what we collect or how we use it,
                        we&apos;ll update this page and bump the
                        effective date at the top. For material changes
                        we&apos;ll also note them on the splash screen
                        on next sign-in.
                    </Body>
                </Section>

                <Section title="8. Contact">
                    <Body>
                        Questions about this policy, or about the data
                        we hold for you?{" "}
                        <MuiLink
                            href={`mailto:${PRIVACY_EMAIL}?subject=${encodeURIComponent("Time2Leave privacy question")}`}
                        >
                            {PRIVACY_EMAIL}
                        </MuiLink>
                        .
                    </Body>
                </Section>
            </Stack>
        </Container>
    );
}

function Section({
    title,
    children,
}: {
    title: string;
    children: React.ReactNode;
}) {
    return (
        <Paper
            elevation={0}
            sx={{ ...glassCardSx, p: { xs: 2.5, md: 3 } }}
        >
            <Stack spacing={1.5}>
                <Typography
                    variant="h6"
                    component="h2"
                    sx={{ fontWeight: 700 }}
                >
                    {title}
                </Typography>
                {children}
            </Stack>
        </Paper>
    );
}

function Body({ children }: { children: React.ReactNode }) {
    return (
        <Typography
            variant="body2"
            color="text.secondary"
            sx={{ lineHeight: 1.6 }}
        >
            {children}
        </Typography>
    );
}

function Bullets({ items }: { items: string[] }) {
    return (
        <Box component="ul" sx={{ pl: 2.5, my: 0 }}>
            {items.map((item) => (
                <Typography
                    key={item}
                    component="li"
                    variant="body2"
                    color="text.secondary"
                    sx={{ lineHeight: 1.6, mb: 0.75 }}
                >
                    {item}
                </Typography>
            ))}
        </Box>
    );
}

export default function PrivacyPage() {
    return (
        <AppShell>
            <PrivacyInner />
        </AppShell>
    );
}
