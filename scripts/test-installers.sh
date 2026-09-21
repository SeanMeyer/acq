#!/usr/bin/env bash
# Regression tests for installer writes to symlinked user configuration.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() { rm -rf "${WORK_DIR}"; }
trap cleanup EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

make_fake_commands() {
    local bin_dir="$1"
    mkdir -p "${bin_dir}"

    cat > "${bin_dir}/pi" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
    list) printf '%s\n' 'npm:pi-mcp-adapter' ;;
    install|remove) ;;
    *) exit 1 ;;
esac
EOF

    cat > "${bin_dir}/omp" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-} ${2:-}" == "config path" ]]; then
    printf '%s\n' "${FAKE_OMP_AGENT_DIR:?}"
    exit 0
fi
if [[ "${1:-}" == "plugin" ]]; then
    exit 0
fi
exit 1
EOF

    cat > "${bin_dir}/uv" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

    chmod +x "${bin_dir}/pi" "${bin_dir}/omp" "${bin_dir}/uv"
}

make_block_only_symlink() {
    local agent_dir="$1" tracked_dir="$2" filename="$3"
    mkdir -p "${agent_dir}" "${tracked_dir}"
    cat > "${tracked_dir}/${filename}" <<'EOF'
<!-- acq:start -->
managed guidance
<!-- acq:end -->
EOF
    chmod 0644 "${tracked_dir}/${filename}"
    ln -s "${tracked_dir}/${filename}" "${agent_dir}/${filename}"
}

assert_link_and_target_preserved() {
    local link="$1" target="$2"
    [[ -L "${link}" ]] || fail "${link} was replaced instead of preserving the symlink"
    [[ -f "${target}" ]] || fail "tracked target ${target} was deleted"
    [[ ! -s "${target}" ]] || fail "tracked target ${target} was not emptied"
}

BIN_DIR="${WORK_DIR}/bin"
make_fake_commands "${BIN_DIR}"

# pi: when AGENTS.md consists only of the managed block, uninstall must not
# delete either a dotfiles symlink or its tracked target.
PI_AGENT_DIR="${WORK_DIR}/pi-agent"
PI_TRACKED_DIR="${WORK_DIR}/pi-dotfiles"
make_block_only_symlink "${PI_AGENT_DIR}" "${PI_TRACKED_DIR}" "AGENTS.md"
printf '%s\n' '{"mcpServers":{"acq":{},"other":{"command":"kept"}}}' > "${PI_AGENT_DIR}/mcp.json"
PATH="${BIN_DIR}:${PATH}" PI_CODING_AGENT_DIR="${PI_AGENT_DIR}" \
    "${REPO_ROOT}/scripts/install-pi.sh" uninstall >/dev/null
assert_link_and_target_preserved \
    "${PI_AGENT_DIR}/AGENTS.md" "${PI_TRACKED_DIR}/AGENTS.md"
[[ "$(jq -r '.mcpServers.other.command' "${PI_AGENT_DIR}/mcp.json")" == "kept" ]] || \
    fail "pi uninstall removed unrelated MCP configuration"

# OMP: same dangerous branch for RULES.md. The fake omp command supplies an
# isolated active profile so the test never touches the developer's real one.
OMP_AGENT_DIR="${WORK_DIR}/omp-agent"
OMP_TRACKED_DIR="${WORK_DIR}/omp-dotfiles"
make_block_only_symlink "${OMP_AGENT_DIR}" "${OMP_TRACKED_DIR}" "RULES.md"
printf '%s\n' \
    '{"mcpServers":{"acq":{},"other":{"command":"kept"}},"disabledServers":["acq:acq"]}' \
    > "${OMP_AGENT_DIR}/mcp.json"
PATH="${BIN_DIR}:${PATH}" FAKE_OMP_AGENT_DIR="${OMP_AGENT_DIR}" \
    "${REPO_ROOT}/scripts/install-omp.sh" uninstall >/dev/null
assert_link_and_target_preserved \
    "${OMP_AGENT_DIR}/RULES.md" "${OMP_TRACKED_DIR}/RULES.md"
[[ "$(jq -r '.mcpServers.other.command' "${OMP_AGENT_DIR}/mcp.json")" == "kept" ]] || \
    fail "OMP uninstall removed unrelated MCP configuration"

# A resource the manifest does not list is inert, which is how the Claude-format
# SessionStart hook silently did nothing under pi. Assert the declaration and
# the files agree in both directions.
for dir in $(jq -r '.pi.extensions // [] | .[]' "${REPO_ROOT}/plugins/acq/package.json"); do
    ext_dir="${REPO_ROOT}/plugins/acq/${dir#./}"
    [[ -d "${ext_dir}" ]] || fail "pi manifest declares ${dir} but no such directory exists"
    compgen -G "${ext_dir}/*.[jt]s" >/dev/null || \
        fail "pi manifest declares ${dir} but it holds no .js or .ts extension"
done
while IFS= read -r ext; do
    jq -e --arg d "./$(dirname "${ext#plugins/acq/}")" \
        '.pi.extensions | index($d)' "${REPO_ROOT}/plugins/acq/package.json" >/dev/null || \
        fail "${ext} is not covered by pi.extensions in plugins/acq/package.json"
done < <(cd "${REPO_ROOT}" && git ls-files 'plugins/acq/extensions/*.js' 'plugins/acq/extensions/*.ts')

printf '%s\n' "installer symlink regression tests passed"
