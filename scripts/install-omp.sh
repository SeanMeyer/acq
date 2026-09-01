#!/usr/bin/env bash
# Install or uninstall acq for OMP (oh-my-pi).
#
# Usage:
#   install-omp.sh install [--team-addr <url>] [--api-key <key>] [--agent-name <name>]
#   install-omp.sh install --local-only
#   install-omp.sh uninstall
#
# OMP reads Claude-format plugins natively, so the plugin itself is installed
# through OMP's marketplace using this repo's existing
# .claude-plugin/marketplace.json. That gives OMP the acq skill and slash
# commands with no duplicated manifest.
#
# The plugin's own MCP entry (registered as "acq:acq") declares no environment,
# so it can only ever run in local-only mode. This script therefore also writes
# an OMP-native MCP entry named "acq" that points at the working tree and
# carries the team API environment, and suppresses "acq:acq" so exactly one set
# of acq tools is exposed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVER_DIR="${REPO_ROOT}/plugins/acq/server"

PLUGIN_REF="acq@acq"
SERVER_NAME="acq"
PLUGIN_SERVER_NAME="acq:acq"

# -- Dependencies. --

for bin in omp jq uv; do
    if ! command -v "${bin}" &>/dev/null; then
        echo "Error: ${bin} is required but not installed." >&2
        exit 1
    fi
done

# -- Argument parsing. --

usage() {
    sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
}

[[ $# -lt 1 ]] && usage

ACTION="$1"
shift

TEAM_ADDR="http://localhost:8742"
API_KEY="default-key"
AGENT_NAME="$(whoami)-omp"
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

# Resolve the active OMP agent directory so named profiles and
# PI_CODING_AGENT_DIR are honoured instead of hardcoding ~/.omp/agent.
AGENT_DIR="$(omp config path)"
if [[ -z "${AGENT_DIR}" || ! "${AGENT_DIR}" = /* ]]; then
    echo "Error: 'omp config path' did not return an absolute path: '${AGENT_DIR}'" >&2
    exit 1
fi
MCP_FILE="${AGENT_DIR}/mcp.json"
MCP_SCHEMA="https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json"

# -- Atomic writes. --
# mcp.json is the user's real config and may hold unrelated servers they added
# by hand. A plain `> file` redirect truncates on open, so an interruption
# between truncate and write would destroy it. Write to a sibling temp file and
# rename instead: rename(2) within one directory is atomic.

TMP_FILE=""
cleanup() { [[ -n "${TMP_FILE}" && -e "${TMP_FILE}" ]] && rm -f "${TMP_FILE}"; return 0; }
trap cleanup EXIT

write_atomic() {
    TMP_FILE="$(mktemp "${MCP_FILE}.tmp.XXXXXX")"
    printf '%s\n' "$1" > "${TMP_FILE}"
    mv -f "${TMP_FILE}" "${MCP_FILE}"
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
    [[ -f "${MCP_FILE}" ]] || write_atomic "$(printf '{}\n')"

    write_atomic "$(jq \
        --arg schema "${MCP_SCHEMA}" \
        --arg name "${SERVER_NAME}" \
        --arg plugin_name "${PLUGIN_SERVER_NAME}" \
        --argjson entry "${entry}" \
        '(.["$schema"] //= $schema)
         | .mcpServers[$name] = $entry
         | .disabledServers = ((.disabledServers // []) + [$plugin_name] | unique)' \
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
    write_atomic "$(jq \
        --arg name "${SERVER_NAME}" \
        --arg plugin_name "${PLUGIN_SERVER_NAME}" \
        'del(.mcpServers[$name])
         | .disabledServers = ((.disabledServers // []) - [$plugin_name])
         | if (.disabledServers | length) == 0 then del(.disabledServers) else . end' \
        "${MCP_FILE}")"
    echo "  Removed MCP server '${SERVER_NAME}' from ${MCP_FILE}"
}

# -- Plugin (skill + slash commands) via OMP's marketplace. --

configure_plugin() {
    # Re-adding an existing marketplace is the normal case on reinstall and is
    # the one failure worth ignoring here.
    if ! omp plugin marketplace add "${REPO_ROOT}" >/dev/null 2>&1; then
        echo "  Marketplace already registered (or add failed); continuing"
    fi
    # An update failure means the catalog may be stale, and the install below
    # would then quietly deliver outdated plugin content — so report it.
    if ! update_err=$(omp plugin marketplace update acq 2>&1 >/dev/null); then
        echo "  Warning: marketplace update failed; installing from cached catalog" >&2
        [[ -n "${update_err}" ]] && echo "    ${update_err}" >&2
    fi
    omp plugin install --force "${PLUGIN_REF}"
}

remove_plugin() {
    if uninstall_err=$(omp plugin uninstall "${PLUGIN_REF}" 2>&1 >/dev/null); then
        echo "  Removed plugin ${PLUGIN_REF}"
    elif [[ "${uninstall_err}" == *"not found"* || "${uninstall_err}" == *"not installed"* ]]; then
        echo "  Plugin ${PLUGIN_REF} was not installed"
    else
        echo "  Warning: could not remove plugin ${PLUGIN_REF}" >&2
        [[ -n "${uninstall_err}" ]] && echo "    ${uninstall_err}" >&2
    fi
    if ! omp plugin marketplace remove acq >/dev/null 2>&1; then
        echo "  Note: marketplace 'acq' was not registered"
    fi
}

# -- Usage guidance (RULES.md). --
# The skill's own description tells the model what acq is, but a skill is only
# consulted once the model decides it is relevant. Searching *before* exploring
# has to be a standing instruction, which for OMP means the user-level
# rulebook. In Claude Code the plugin's SessionStart hook injects this; OMP
# hooks are JS/TS modules and do not run that shell hook, so it is done here.

RULES_MARKER_START="<!-- acq:start -->"
RULES_MARKER_END="<!-- acq:end -->"

read -r -d '' RULES_BLOCK <<'BLOCK' || true
<!-- acq:start -->
Before a nontrivial investigation, search ACQ when prior experience could save
time. Treat results as leads and verify them against the current system.
Afterward, consider saving knowledge that was hard to obtain and likely to save
substantial future work. Skip facts quickly recovered from code or docs and
facts useful only to the current task.
<!-- acq:end -->
BLOCK

configure_rules() {
    local rules_file="${AGENT_DIR}/RULES.md"
    mkdir -p "${AGENT_DIR}"

    if [[ -f "${rules_file}" ]] && grep -qxF "${RULES_MARKER_START}" "${rules_file}"; then
        if ! grep -qxF "${RULES_MARKER_END}" "${rules_file}"; then
            echo "  Warning: ${rules_file} has an acq start marker but no end marker — leaving it alone" >&2
            return 0
        fi
        local tmp_file
        tmp_file=$(mktemp)
        awk -v start="${RULES_MARKER_START}" '$0 == start { exit } { print }' "${rules_file}" > "${tmp_file}"
        printf '%s\n' "${RULES_BLOCK}" >> "${tmp_file}"
        awk -v end="${RULES_MARKER_END}" 'after { print } $0 == end { after=1 }' "${rules_file}" >> "${tmp_file}"
        mv "${tmp_file}" "${rules_file}"
        echo "  Updated acq guidance in ${rules_file}"
        return 0
    fi

    if [[ -s "${rules_file}" ]]; then
        printf '\n%s\n' "${RULES_BLOCK}" >> "${rules_file}"
        echo "  Appended acq guidance to ${rules_file}"
    else
        printf '%s\n' "${RULES_BLOCK}" > "${rules_file}"
        echo "  Created ${rules_file} with acq guidance"
    fi
}

remove_rules() {
    local rules_file="${AGENT_DIR}/RULES.md"
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
        rm -f "${rules_file}"
        echo "  Removed ${rules_file} (no other content)"
    else
        printf '%s\n' "${tmp}" > "${rules_file}"
        echo "  Removed acq guidance from ${rules_file}"
    fi
}

# -- Dispatch. --

case "${ACTION}" in
    install)
        echo "Installing acq for OMP..."
        configure_plugin
        configure_mcp
        configure_rules
        echo ""
        echo "Done. Restart OMP, or run /mcp reload in a live session."
        ;;
    uninstall)
        echo "Removing acq for OMP..."
        remove_plugin
        remove_mcp
        remove_rules
        echo ""
        echo "Done."
        ;;
    *)
        usage
        ;;
esac
