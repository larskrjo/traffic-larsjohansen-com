# zsh completion for the t2l CLI.
#
# Sourced from ~/.zshrc via the block setup.sh writes. Designed to be
# fully self-contained — does its own `compinit` if the surrounding
# shell hasn't already, so `source`-ing this file is enough to enable
# tab completion regardless of what else lives in the user's rc.

# Make sure `compdef` is available. Most modern .zshrc setups (oh-my-zsh,
# prezto, plain) call compinit already; this is a defensive fallback.
if ! whence compdef >/dev/null 2>&1; then
    autoload -Uz compinit
    compinit -u
fi

_t2l() {
    local context state state_descr line
    typeset -A opt_args

    _arguments -C \
        '1: :->verb' \
        '2: :->target' \
        '*::flag:->flags'

    case $state in
        verb)
            _values 'command' \
                'up[start / restart something locally]' \
                'deploy[push something to production]' \
                'help[show usage]'
            ;;

        target)
            case $words[2] in
                up)
                    _values 'target' \
                        'be[local backend (MySQL + FastAPI in Docker)]' \
                        'fe[local web (Vite dev server)]' \
                        'ios[local iOS (Expo Metro)]'
                    ;;
                deploy)
                    _values 'target' \
                        'be[backend on EC2 (ssh + docker rebuild)]' \
                        'fe[web on S3 + CloudFront]' \
                        'app[mobile app via EAS (OTA or build+submit)]'
                    ;;
            esac
            ;;

        flags)
            case "$words[2] $words[3]" in
                'up be')
                    _arguments \
                        '--rebuild[force rebuild + recreate API container]'
                    ;;
                'up fe')
                    # takes no flags
                    ;;
                'up ios')
                    _arguments \
                        '--rebuild[full native rebuild via expo prebuild + Xcode]' \
                        '--device[override iOS device for --rebuild]:device name:'
                    ;;
                'deploy be')
                    _arguments \
                        '--host[SSH target (alias or user@host)]:host:'
                    ;;
                'deploy fe')
                    # takes no flags
                    ;;
                'deploy app')
                    _arguments \
                        '(--build)--ota[OTA update via EAS Update (JS-only)]' \
                        '(--ota)--build[full native EAS build (production profile)]' \
                        '--platform[target platform]:platform:(ios android both)' \
                        '--message[OTA release note]:message:' \
                        '--submit[after --build, submit latest build to store]'
                    ;;
            esac
            ;;
    esac
}

compdef _t2l t2l
