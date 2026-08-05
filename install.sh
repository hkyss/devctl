#!/usr/bin/env sh
set -eu

repo_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

path_contains() {
  case ":${PATH:-}:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

default_install_dir() {
  if [ -n "${DEVCTL_INSTALL_DIR:-}" ]; then
    printf '%s\n' "${DEVCTL_INSTALL_DIR}"
    return 0
  fi

  for dir in /usr/local/bin /opt/homebrew/bin "${HOME}/.local/bin"; do
    if path_contains "${dir}" && [ -d "${dir}" ]; then
      printf '%s\n' "${dir}"
      return 0
    fi
  done

  old_ifs="${IFS}"
  IFS=:
  for dir in ${PATH:-}; do
    IFS="${old_ifs}"
    if [ -n "${dir}" ] && [ -d "${dir}" ] && [ -w "${dir}" ]; then
      printf '%s\n' "${dir}"
      return 0
    fi
    IFS=:
  done
  IFS="${old_ifs}"

  printf '%s\n' "${HOME}/.local/bin"
}

target_dir="$(default_install_dir)"
target="${target_dir}/devctl"

mkdir -p "${target_dir}"
chmod +x "${repo_dir}/devctl" "${repo_dir}/bin/devctl"
if [ -w "${target_dir}" ]; then
  ln -sf "${repo_dir}/devctl" "${target}"
else
  command -v sudo >/dev/null 2>&1 || {
    echo "Cannot write to ${target_dir} and sudo is not available." >&2
    exit 1
  }
  sudo ln -sf "${repo_dir}/devctl" "${target}"
fi

echo "Installed dockerized devctl -> ${target}"
path_contains "${target_dir}" || {
  echo "Warning: ${target_dir} is not in PATH. Set DEVCTL_INSTALL_DIR to a directory that is already in PATH." >&2
  exit 1
}
command -v devctl >/dev/null 2>&1 || {
  echo "Warning: devctl is installed, but the current shell cannot resolve it." >&2
  exit 1
}
