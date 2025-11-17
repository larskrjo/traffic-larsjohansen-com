import { createTheme } from '@mui/material/styles';

export const theme = createTheme({
    cssVariables: {
        colorSchemeSelector: "[data-mui-color-scheme='%s']",
    },
    colorSchemes: {
        light: {
            palette: {
                mode: 'light',
                primary: { main: '#1976d2' },
                secondary: { main: '#9c27b0' },
            },
        }
    },
});