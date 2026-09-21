#!/usr/bin/env bash
# Install or uninstall acq for pi (@earendil-works/pi-coding-agent).
#
# Usage:
#   install-pi.sh install [--team-addr <url>] [--api-key <key>] [--agent-name <name>]
#   install-pi.sh install --local-only
#   install-pi.sh uninstall
#
# Unlike OMP, upstream pi does not read Claude-format plugin manifests. It has
# its own package format instead: a package.json carrying a "pi" key that lists
# skills, prompts, extensions, and themes. plugins/acq/package.json declares the
# acq skill, slash commands, and reminder extension that way, and `pi install`
# on a local path resolves it in place rather than copying, so edits to the
# working tree take effect without reinstalling.
#
# pi names slash commands after the file, ignoring frontmatter, so the commands
# are /acq-reflect and /acq-status here. OMP reads the frontmatter and exposes
# the same commands as /acq:reflect and /acq:status.
#
# The pi manifest has no field for MCP servers, so this script also writes an
# entry to pi's mcp.json pointing at the working tree. pi core has no MCP
# support of its own -- nothing outside its bundled chunks reads mcp.json --
# so that entry is inert until the pi-mcp-adapter extension is present. The
# installer adds it when missing, otherwise the skill would tell the model to
# search ACQ with no tool able to do it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLUGIN_DIR="${REPO_ROOT}/plugins/acq"
SERVER_DIR="${PLUGIN_DIR}/server"

SERVER_NAME="acq"
MCP_ADAPTER="pi-mcp-adapter"

# -- Dependencies. --

for bin in pi jq uv; do
    if ! command -v "${bin}" &>/dev/null; then
        echo "Error: ${bin} is required but not installed." >&2
        exit 1
    fi
done

# -- Argument parsing. --

usage() {
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
    exit 1
}

[[ $# -lt 1 ]] && usage

ACTION="$1"
shift

TEAM_ADDR="http://localhost:8742"
API_KEY="default-key"
AGENT_NAME="$(whoami)-pi"
LOCAL_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --team-addr)  TEAM_ADDR="${2:?--team-addr needs a value}"; shift 2 ;;
        --api-key)    API_KEY="${2:?--api-key needs a value}"; shift 2 ;;
        --agent-name) AGENT_NAME="${2:?--agent-name needs a value}"; shift 2 ;;
        --local-only) LOCAL_ONLY=1; shift ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# pi resolves its agent directory from PI_CODING_AGENT_DIR, falling back to
# ~/.pi/agent. Mirror that here so a custom location is honoured.
AGENT_DIR="${PI_CODING_AGENT_DIR:-${HOME}/.pi/agent}"
MCP_FILE="${AGENT_DIR}/mcp.json"

# -- File writes. --
# mcp.json and AGENTS.md are the user's real config and may hold unrelated
# content they added by hand. A plain `> file` redirect truncates on open, so
# an interruption between truncate and write would destroy it. Write to a
# sibling temp file and rename instead: rename(2) within one directory is
# atomic, and staying in the same directory keeps it on one filesystem.

TMP_FILE=""
cleanup() { [[ -n "${TMP_FILE}" && -e "${TMP_FILE}" ]] && rm -f "${TMP_FILE}"; return 0; }
trap cleanup EXIT

# Follow a symlink chain to the real file. These paths are often symlinks into
# a dotfiles repo, and renaming over the link would replace it with a regular
# file, silently orphaning the version-controlled original that the user still
# believes is in effect.
resolve_link() {
    local path="$1" target hops=0
    while [[ -L "${path}" ]]; do
        if (( ++hops > 40 )); then
            echo "Error: symlink loop resolving $1" >&2
            return 1
        fi
        target="$(readlink "${path}")"
        if [[ "${target}" = /* ]]; then
            path="${target}"
        else
            path="$(cd "$(dirname "${path}")" && pwd)/${target}"
        fi
    done
    printf '%s\n' "${path}"
}

# BSD stat first, GNU stat second.
file_mode() {
    stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1" 2>/dev/null
}

# rename(2) makes the destination adopt the temp file's mode, which mktemp
# creates as 0600, so an existing file's permissions have to be carried over
# explicitly or every run would silently tighten them.
write_file() {
    local dest mode=""
    dest="$(resolve_link "$1")" || return 1
    mkdir -p "$(dirname "${dest}")"
    if [[ -f "${dest}" ]]; then
        mode="$(file_mode "${dest}")"
    fi
    TMP_FILE="$(mktemp "${dest}.tmp.XXXXXX")"
    if [[ "${3:-}" == "empty" ]]; then
        : > "${TMP_FILE}"
    else
        printf '%s\n' "$2" > "${TMP_FILE}"
    fi
    if [[ -n "${mode}" ]]; then
        chmod "${mode}" "${TMP_FILE}"
    fi
    mv -f "${TMP_FILE}" "${dest}"
    TMP_FILE=""
}

# -- MCP configuration. --

configure_mcp() {
    local entry env_json
    if [[ ${LOCAL_ONLY} -eq 1 ]]; then
        env_json='{}'
    else
        env_json=$(jq -n \
            --arg addr "${TEAM_ADDR}" \
            --arg key "${API_KEY}" \
            --arg agent "${AGENT_NAME}" \
            '{ ACQ_TEAM_ADDR: $addr, ACQ_TEAM_API_KEY: $key, ACQ_AGENT_NAME: $agent }')
    fi

    entry=$(jq -n \
        --arg dir "${SERVER_DIR}" \
        --argjson env "${env_json}" \
        '{ command: "uv", args: ["run", "--directory", $dir, "acq-mcp-server"] }
         + (if ($env | length) > 0 then { env: $env } else {} end)')

    mkdir -p "${AGENT_DIR}"
    [[ -f "${MCP_FILE}" ]] || write_file "${MCP_FILE}" "{}"

    write_file "${MCP_FILE}" "$(jq \
        --arg name "${SERVER_NAME}" \
        --argjson entry "${entry}" \
        '.mcpServers[$name] = $entry' \
        "${MCP_FILE}")"
    echo "  Configured MCP server '${SERVER_NAME}' in ${MCP_FILE}"
    if [[ ${LOCAL_ONLY} -eq 1 ]]; then
        echo "  Team API: disabled (local-only)"
    else
        echo "  Team API: ${TEAM_ADDR} as agent '${AGENT_NAME}'"
    fi
}

remove_mcp() {
    [[ -f "${MCP_FILE}" ]] || return 0
    write_file "${MCP_FILE}" "$(jq --arg name "${SERVER_NAME}" 'del(.mcpServers[$name])' "${MCP_FILE}")"
    echo "  Removed MCP server '${SERVER_NAME}' from ${MCP_FILE}"
}

# -- Package (skill + slash commands) via pi's package manager. --

configure_package() {
    pi install "${PLUGIN_DIR}"
    echo "  Installed pi package from ${PLUGIN_DIR}"
}

# Not removed on uninstall: other packages may rely on the adapter, and it is
# not ours to take away.
configure_adapter() {
    if pi list 2>/dev/null | grep -q "${MCP_ADAPTER}"; then
        echo "  ${MCP_ADAPTER} already installed"
        return 0
    fi
    echo "  Installing ${MCP_ADAPTER} (pi has no native MCP support)"
    pi install "npm:${MCP_ADAPTER}"
}

remove_package() {
    if remove_err=$(pi remove "${PLUGIN_DIR}" 2>&1 >/dev/null); then
        echo "  Removed pi package ${PLUGIN_DIR}"
    else
        echo "  Warning: could not remove pi package ${PLUGIN_DIR}" >&2
        [[ -n "${remove_err}" ]] && echo "    ${remove_err}" >&2
    fi
}

# -- Usage guidance (AGENTS.md). --
# The skill's own description tells the model what acq is, but a skill is only
# consulted once the model decides it is relevant. Searching *before* exploring
# has to be a standing instruction, which for pi means the user-level AGENTS.md.
#
# plugins/acq/extensions/acq-reminder.js also injects this once per session, the
# way the Claude-format SessionStart hook does. Both are kept: the extension is
# the salient nudge, and AGENTS.md still covers anyone running the skill without
# the package or with extensions disabled.
#
# The `mcp` adapter sentence is pi-specific and deliberately absent from
# install-omp.sh: pi reaches MCP servers through the pi-mcp-adapter extension,
# whereas OMP and Claude Code expose MCP tools directly.

RULES_MARKER_START="<!-- acq:start -->"
RULES_MARKER_END="<!-- acq:end -->"

read -r -d '' RULES_BLOCK <<'BLOCK' || true
<!-- acq:start -->
Before a nontrivial investigation, search ACQ when prior experience could save
time. ACQ tools are available through the `mcp` adapter. Search returns
questions only, so open relevant threads to read the answers. Treat answers as
leads and verify them against the current system. Afterward, consider saving
knowledge that was hard to obtain and likely to save substantial future work.
Skip facts quickly recovered from code or docs and facts useful only to the
current task.
<!-- acq:end -->
BLOCK

configure_rules() {
    local rules_file="${AGENT_DIR}/AGENTS.md"
    mkdir -p "${AGENT_DIR}"

    if [[ -f "${rules_file}" ]] && grep -qxF "${RULES_MARKER_START}" "${rules_file}"; then
        if ! grep -qxF "${RULES_MARKER_END}" "${rules_file}"; then
            echo "  Warning: ${rules_file} has an acq start marker but no end marker — leaving it alone" >&2
            return 0
        fi
        local before after
        before="$(awk -v start="${RULES_MARKER_START}" '$0 == start { exit } { print }' "${rules_file}")"
        after="$(awk -v end="${RULES_MARKER_END}" 'after { print } $0 == end { after=1 }' "${rules_file}")"
        local parts=()
        # Command substitution strips trailing newlines, so re-add the blank
        # line that separated the user's content from the block.
        if [[ -n "${before}" ]]; then parts+=("${before}" ""); fi
        parts+=("${RULES_BLOCK}")
        if [[ -n "${after}" ]]; then parts+=("${after}"); fi
        write_file "${rules_file}" "$(printf '%s\n' "${parts[@]}")"
        echo "  Updated acq guidance in ${rules_file}"
        return 0
    fi

    if [[ -s "${rules_file}" ]]; then
        write_file "${rules_file}" "$(cat "${rules_file}"; printf '\n%s' "${RULES_BLOCK}")"
        echo "  Appended acq guidance to ${rules_file}"
    else
        write_file "${rules_file}" "${RULES_BLOCK}"
        echo "  Created ${rules_file} with acq guidance"
    fi
}

remove_rules() {
    local rules_file="${AGENT_DIR}/AGENTS.md"
    [[ -f "${rules_file}" ]] || return 0
    grep -qxF "${RULES_MARKER_START}" "${rules_file}" || return 0

    if ! grep -qxF "${RULES_MARKER_END}" "${rules_file}"; then
        echo "  Warning: ${rules_file} has an acq start marker but no end marker — leaving it alone" >&2
        return 0
    fi

    local tmp
    tmp=$(awk -v start="${RULES_MARKER_START}" -v end="${RULES_MARKER_END}" '
        $0 == start { skip=1; next }
        $0 == end   { skip=0; next }
        skip { next }
        { n++; lines[n] = $0 }
        END {
            last = n
            while (last > 0 && lines[last] ~ /^[[:space:]]*$/) last--
            for (i = 1; i <= last; i++) print lines[i]
        }
    ' "${rules_file}")

    if [[ -z "${tmp}" ]]; then
        # The marker proves we managed the block, not that we created the file.
        # Preserve a symlinked dotfiles target (and an unproven regular file)
        # rather than deleting user-owned configuration.
        write_file "${rules_file}" "" empty
        echo "  Cleared acq guidance from ${rules_file} (no other content)"
    else
        write_file "${rules_file}" "${tmp}"
        echo "  Removed acq guidance from ${rules_file}"
    fi
}

# -- Dispatch. --

case "${ACTION}" in
    install)
        echo "Installing acq for pi..."
        configure_package
        configure_adapter
        configure_mcp
        configure_rules
        echo ""
        echo "Done. Restart pi. Slash commands are /acq-reflect and /acq-status."
        ;;
    uninstall)
        echo "Removing acq for pi..."
        remove_package
        remove_mcp
        remove_rules
        echo ""
        echo "Done."
        ;;
    *)
        usage
        ;;
esac
