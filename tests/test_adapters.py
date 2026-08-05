import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from devctl.adapters import DockerComposeAdapter, adapter_for, published_ports
from devctl.errors import DevctlError
from devctl.profiles import PublishTarget

from .helpers import TempDirTestCase, make_profile, make_settings


class AdapterTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.settings = make_settings(self.tmp_path)

    def test_command_up_includes_env_file_build_and_remove_orphans(self) -> None:
        profile = make_profile(env_file="docker/.env", compose_file="compose.yml", build=True)
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "--env-file", "docker/.env", "-f", "compose.yml", "up", "-d", "--build", "--remove-orphans"],
            adapter.command_up(),
        )

    def test_command_up_passes_every_compose_file_in_order(self) -> None:
        profile = make_profile(compose_files=["docker/base.yml", "docker/dev.yml"])
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "-f", "docker/base.yml", "-f", "docker/dev.yml", "up", "-d", "--remove-orphans"],
            adapter.command_up(),
        )

    def test_publish_profile_appends_generated_override_as_last_file(self) -> None:
        profile = make_profile(
            name="app",
            compose_files=["compose.yml"],
            http_port_env=None,
            publish=PublishTarget(service="web", container_port=80),
        )
        adapter = DockerComposeAdapter(self.settings, profile)

        command = adapter.command_up()

        override = str(self.settings.state_dir / "overrides" / "app.yml")
        self.assertEqual(["-f", "compose.yml", "-f", override], command[2:6])
        self.assertTrue((self.settings.state_dir / "overrides" / "app.yml").exists())

    def test_env_mode_profile_with_compose_override_appends_generated_override(self) -> None:
        profile = make_profile(
            name="app",
            compose_files=["compose.yml"],
            compose_override={"services": {"db": {"image": "mysql:8.0.33"}}},
        )
        adapter = DockerComposeAdapter(self.settings, profile)

        command = adapter.command_up()

        override = str(self.settings.state_dir / "overrides" / "app.yml")
        self.assertEqual(["-f", "compose.yml", "-f", override], command[2:6])

    def test_publish_profile_env_has_no_http_port_variable(self) -> None:
        profile = make_profile(
            name="app",
            http_port_env=None,
            publish=PublishTarget(service="web", container_port=80),
        )
        adapter = DockerComposeAdapter(self.settings, profile)

        env = adapter.env(50003, [])

        self.assertNotIn("PORT_HTTP", env)
        self.assertEqual("50003", env["DEVCTL_BACKEND_PORT"])

    def test_publish_profile_up_writes_real_port_into_override(self) -> None:
        profile = make_profile(
            name="app",
            http_port_env=None,
            publish=PublishTarget(service="web", container_port=80),
        )
        adapter = DockerComposeAdapter(self.settings, profile)

        with patch.object(adapter, "_run_streaming", return_value=0) as run, open(os.devnull, "ab") as log_file:
            exit_code = adapter.up(50003, [], log_file=log_file)

        self.assertEqual(0, exit_code)
        run.assert_called_once()
        content = (self.settings.state_dir / "overrides" / "app.yml").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:50003:80", content)

    def test_command_up_omits_build_when_disabled(self) -> None:
        profile = make_profile(build=False)
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertNotIn("--build", adapter.command_up())

    def test_command_pre_up_wraps_compose_run(self) -> None:
        profile = make_profile(env_file="docker/.env", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "--env-file", "docker/.env", "-f", "compose.yml", "run", "--rm", "cms", "composer", "install"],
            adapter.command_pre_up(["cms", "composer", "install"]),
        )

    def test_env_sets_ports_publish_specs_domain_and_project_name(self) -> None:
        profile = make_profile(
            name="app",
            http_port_env="PORT_HTTP",
            extra_port_envs=["PORT_DB", "PORT_REDIS"],
            host_prefixed_port_envs={"PORT_HTTP", "PORT_DB"},
            publish_envs={"REDIS_PUBLISH": {"source": "PORT_REDIS", "target": 6379}},
            env={"APP_ENV": "local"},
        )
        adapter = DockerComposeAdapter(self.settings, profile)

        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            env = adapter.env(8080, [3306, 6379])

        self.assertEqual("127.0.0.1:8080", env["PORT_HTTP"])
        self.assertEqual("127.0.0.1:3306", env["PORT_DB"])
        self.assertEqual("6379", env["PORT_REDIS"])
        self.assertEqual("127.0.0.1:6379:6379", env["REDIS_PUBLISH"])
        self.assertEqual("local", env["APP_ENV"])
        self.assertEqual("app.localhost", env["DEVCTL_DOMAIN"])
        self.assertEqual("http://app.localhost", env["DEVCTL_URL"])
        self.assertEqual("devctl_app_alice", env["COMPOSE_PROJECT_NAME"])

    def test_env_respects_explicit_compose_project_name(self) -> None:
        profile = make_profile(compose_project_name="explicit")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual("explicit", adapter.env(8080, [])["COMPOSE_PROJECT_NAME"])

    def test_adapter_for_rejects_unknown_adapter(self) -> None:
        with self.assertRaisesRegex(DevctlError, "unsupported adapter"):
            adapter_for(self.settings, make_profile(adapter="unknown"))

    def test_command_exec_includes_env_file_and_service(self) -> None:
        profile = make_profile(env_file="docker/.env", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "--env-file", "docker/.env", "-f", "compose.yml", "exec", "cms", "sh"],
            adapter.command_exec("cms", ["sh"], tty=True),
        )

    def test_command_exec_disables_tty_with_flag(self) -> None:
        profile = make_profile(compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "-f", "compose.yml", "exec", "-T", "cms", "ls"],
            adapter.command_exec("cms", ["ls"], tty=False),
        )

    def test_command_ps_ids_includes_env_file(self) -> None:
        profile = make_profile(env_file="docker/.env", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "--env-file", "docker/.env", "-f", "compose.yml", "ps", "-q"],
            adapter.command_ps_ids(),
        )

    @patch("devctl.adapters.subprocess.run")
    def test_container_ids_parses_stdout_lines(self, run_mock) -> None:
        run_mock.return_value.stdout = "abc123\ndef456\n"
        profile = make_profile(name="app", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            ids = adapter.container_ids()

        self.assertEqual(["abc123", "def456"], ids)
        call_kwargs = run_mock.call_args.kwargs
        self.assertEqual("devctl_app_alice", call_kwargs["env"]["COMPOSE_PROJECT_NAME"])

    @patch("devctl.adapters.subprocess.run")
    def test_container_ids_empty_when_not_running(self, run_mock) -> None:
        run_mock.return_value.stdout = ""
        profile = make_profile(compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual([], adapter.container_ids())

    def test_command_logs_includes_service_since_and_tail(self) -> None:
        profile = make_profile(env_file="docker/.env", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            [
                "docker",
                "compose",
                "--env-file",
                "docker/.env",
                "-f",
                "compose.yml",
                "logs",
                "-f",
                "--since",
                "10m",
                "--tail",
                "50",
                "cms",
                "queue",
            ],
            adapter.command_logs(follow=True, services=["cms", "queue"], since="10m", tail=50),
        )

    def test_command_logs_omits_optional_flags_when_unset(self) -> None:
        profile = make_profile(compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        self.assertEqual(
            ["docker", "compose", "-f", "compose.yml", "logs"],
            adapter.command_logs(follow=False, services=[], since=None, tail=None),
        )

    @patch("devctl.adapters.subprocess.run")
    def test_logs_runs_with_project_env_and_propagates_exit_code(self, run_mock) -> None:
        run_mock.return_value.returncode = 4
        profile = make_profile(name="app", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            exit_code = adapter.logs(follow=False, services=["cms"], since=None, tail=None)

        self.assertEqual(4, exit_code)
        call_kwargs = run_mock.call_args.kwargs
        self.assertEqual("devctl_app_alice", call_kwargs["env"]["COMPOSE_PROJECT_NAME"])

    @patch("devctl.adapters.subprocess.run")
    def test_exec_runs_with_project_env_and_propagates_exit_code(self, run_mock) -> None:
        run_mock.return_value.returncode = 7
        profile = make_profile(name="app", compose_file="compose.yml")
        adapter = DockerComposeAdapter(self.settings, profile)

        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            exit_code = adapter.exec("cms", ["ls"], tty=True)

        self.assertEqual(7, exit_code)
        call_kwargs = run_mock.call_args.kwargs
        self.assertEqual("devctl_app_alice", call_kwargs["env"]["COMPOSE_PROJECT_NAME"])
        self.assertEqual(profile.path, call_kwargs["cwd"])
        self.assertNotIn("stdout", call_kwargs)


class PublishedPortsTests(TempDirTestCase):
    def _result(self, returncode: int, stdout: str):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    @patch("devctl.adapters.subprocess.run")
    def test_reads_published_ports_from_ndjson_output(self, run_mock) -> None:
        run_mock.return_value = self._result(
            0,
            "\n".join(
                [
                    json.dumps({"Service": "cms", "Publishers": [{"PublishedPort": 0, "TargetPort": 9000}]}),
                    json.dumps({"Service": "nginx", "Publishers": [{"PublishedPort": 18080, "TargetPort": 80}]}),
                    json.dumps({"Service": "mysql", "Publishers": [{"PublishedPort": 13306, "TargetPort": 3306}]}),
                ]
            ),
        )

        self.assertEqual({18080, 13306}, published_ports("devctl_app_alice"))
        self.assertEqual(
            ["docker", "compose", "-p", "devctl_app_alice", "ps", "--format", "json"],
            run_mock.call_args.args[0],
        )

    @patch("devctl.adapters.subprocess.run")
    def test_reads_published_ports_from_json_array_output(self, run_mock) -> None:
        run_mock.return_value = self._result(
            0,
            json.dumps([{"Service": "nginx", "Publishers": [{"PublishedPort": 18080, "TargetPort": 80}]}]),
        )

        self.assertEqual({18080}, published_ports("devctl_app_alice"))

    @patch("devctl.adapters.subprocess.run")
    def test_docker_failure_and_garbage_degrade_to_no_reclaimable_ports(self, run_mock) -> None:
        run_mock.return_value = self._result(1, "")
        self.assertEqual(set(), published_ports("devctl_app_alice"))

        run_mock.return_value = self._result(0, "not json\n")
        self.assertEqual(set(), published_ports("devctl_app_alice"))

        run_mock.return_value = self._result(0, "")
        self.assertEqual(set(), published_ports("devctl_app_alice"))
