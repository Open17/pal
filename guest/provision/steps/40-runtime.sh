# The Pal runtime in its own virtual environment.

install -d "$PAL_ROOT/bin"
install -m 0755 "$PAL_SRC"/guest/system/bin/* "$PAL_ROOT/bin/"

[[ -x $PAL_VENV/bin/python ]] || python3 -m venv "$PAL_VENV"
"$PAL_VENV/bin/pip" install --quiet --upgrade pip
"$PAL_VENV/bin/pip" install --quiet --upgrade "$PAL_SRC/runtime"
ln -sf "$PAL_VENV/bin/pal" /usr/local/bin/pal
for tool in pal-open pal-screen pal-windows; do
    ln -sf "$PAL_ROOT/bin/$tool" "/usr/local/bin/$tool"
done

# The agent SDK ships its own CLI. Expose it so `claude login` and
# `claude setup-token` can be run inside the VM.
cli=$("$PAL_VENV/bin/python" - <<'PY'
import pathlib, claude_agent_sdk
print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")
PY
)
if [[ -x $cli ]]; then
    ln -sf "$cli" /usr/local/bin/claude
    log "agent CLI: $(/usr/local/bin/claude --version 2>/dev/null || echo unknown version)"
else
    warn "the agent SDK did not include its CLI; set [agent] cli_path in pal.toml"
fi

as_pal env PAL_CONFIG_DIR="$PAL_CONFIG" "$PAL_VENV/bin/pal" config check
