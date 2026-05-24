# bash completion for the t2l CLI.
#
# Sourced from ~/.bashrc (or ~/.bash_profile on macOS) via the block
# setup.sh writes. Plain-bash only — no dependence on bash-completion's
# `_init_completion` helper, so it works on default macOS bash 3.2 too.

_t2l() {
    local cur prev verb target
    cur="${COMP_WORDS[COMP_CWORD]}"
    verb="${COMP_WORDS[1]:-}"
    target="${COMP_WORDS[2]:-}"

    # Position 1: the verb itself.
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "up deploy help --help -h" -- "$cur") )
        return
    fi

    # Position 2: the target, depends on verb.
    if [[ $COMP_CWORD -eq 2 ]]; then
        case "$verb" in
            up)     COMPREPLY=( $(compgen -W "be fe ios" -- "$cur") ) ;;
            deploy) COMPREPLY=( $(compgen -W "be fe app" -- "$cur") ) ;;
        esac
        return
    fi

    # Position 3+: flags, depend on verb + target.
    case "$verb $target" in
        'up be')
            COMPREPLY=( $(compgen -W "--rebuild" -- "$cur") )
            ;;
        'up ios')
            COMPREPLY=( $(compgen -W "--rebuild --device" -- "$cur") )
            ;;
        'deploy be')
            COMPREPLY=( $(compgen -W "--host" -- "$cur") )
            ;;
        'deploy app')
            # --platform takes a value; complete the value when --platform
            # is the previous word.
            prev="${COMP_WORDS[COMP_CWORD-1]}"
            case "$prev" in
                --platform) COMPREPLY=( $(compgen -W "ios android both" -- "$cur") ); return ;;
            esac
            COMPREPLY=( $(compgen -W "--ota --build --platform --message --submit" -- "$cur") )
            ;;
    esac
}

complete -F _t2l t2l
