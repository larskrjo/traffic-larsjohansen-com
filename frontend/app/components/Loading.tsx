import {CircularProgress, Stack, Typography} from "@mui/material";

export default function Loading() {
    return (
            <Stack
                alignItems="center"
                justifyContent="center"
                sx={{
                    minHeight: "70vh",
                    gap: 3,
                }}
            >
                <CircularProgress
                    size={90}
                    thickness={4.5}
                />
                <Typography
                    variant="h4"
                    fontWeight={600}
                    color="text.secondary"
                >
                    Loading...
                </Typography>
            </Stack>
    );
}