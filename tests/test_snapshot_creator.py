"""
Copyright 2021 Gandi SAS

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

SPDX-License-Identifier: Apache-2.0
"""
import argparse
import datetime
import sys

import pytest

from dateutil.relativedelta import relativedelta

import cinder_snapshooter.snapshot_creator

from fixtures import FakeSnapshot, FakeVolume


@pytest.mark.parametrize("success", [True, False])
def test_cli(mocker, faker, success):
    mocker.patch("cinder_snapshooter.snapshot_creator.process_volumes")
    mocker.patch("sys.exit")
    cinder_snapshooter.snapshot_creator.process_volumes.return_value = success
    fake_args = argparse.Namespace(
        dry_run=faker.boolean(),
        all_projects=faker.boolean(),
        os_client=mocker.MagicMock(),
    )
    cinder_snapshooter.snapshot_creator.cli(fake_args)
    cinder_snapshooter.snapshot_creator.process_volumes.assert_called_once_with(
        fake_args.os_client,
        fake_args.dry_run,
        fake_args.all_projects,
    )
    if not success:
        sys.exit.assert_called_once_with(1)


@pytest.mark.parametrize(
    "all_projects", [True, False], ids=["single_project", "all_projects"]
)
@pytest.mark.parametrize("dry_run", [True, False], ids=["dry_run", "real_run"])
@pytest.mark.parametrize("success", [True, False])
def test_process_volumes(mocker, faker, log, all_projects, dry_run, success):
    os_client = mocker.MagicMock()
    mocker.patch("cinder_snapshooter.snapshot_creator.create_snapshot_if_needed")

    def fake_volume(suitable):
        if suitable:
            status = ["in-use", "available"]
            metadata = [{"automatic_snapshots": "true"}]
        else:
            status = [
                "creating",
                "attaching",
                "deleting",
                "error",
                "error_deleting",
                "backing-up",
                "restoring-backup",
                "error_restoring",
                "in-use",
                "available",
            ]
            metadata = [{"automatic_snapshots": "false"}, {}]
        return FakeVolume(
            id=faker.uuid4(),
            status=faker.random_element(status),
            metadata=faker.random_element(metadata),
        )

    volumes = [fake_volume(False) for i in range(faker.random_int(max=10))]
    ok_volumes = [fake_volume(True) for i in range(faker.random_int(max=10))]

    nok_volumes = []
    if not success:
        nok_volumes = [fake_volume(True) for i in range(faker.random_int(max=10))]
    ok_volumes += nok_volumes
    volumes += ok_volumes

    def create_snapshot_if_needed(ivolume, _client, _all_projects, _dry_run):
        if ivolume in nok_volumes:
            raise Exception()
        return 1

    os_client.block_storage.volumes.return_value = volumes
    cinder_snapshooter.snapshot_creator.create_snapshot_if_needed.side_effect = (
        create_snapshot_if_needed
    )

    assert (
        cinder_snapshooter.snapshot_creator.process_volumes(
            os_client, dry_run, all_projects
        )
        == success
    )
    if not all_projects:
        all_projects = None

    assert (
        cinder_snapshooter.snapshot_creator.create_snapshot_if_needed.call_count
        == len(ok_volumes)
    )
    for volume in ok_volumes:
        cinder_snapshooter.snapshot_creator.create_snapshot_if_needed.assert_any_call(
            volume,
            os_client,
            all_projects,
            dry_run,
        )

    os_client.block_storage.volumes.assert_called_once_with(all_projects=all_projects)
    assert log.has(
        "All volumes processed",
        errors=len(nok_volumes),
        snapshot_created=len(ok_volumes) - len(nok_volumes),
    )


@pytest.mark.parametrize(
    "all_projects", [None, True], ids=["single_project", "all_projects"]
)
@pytest.mark.parametrize("dry_run", [False, True], ids=["real_run", "dry_run"])
@pytest.mark.parametrize(
    "last_snapshot", ["never", "last_year", "in_year", "in_month", "in_day"]
)
def test_create_snapshot_if_needed(
    mocker, faker, time_machine, all_projects, dry_run, last_snapshot
):
    volume = FakeVolume(
        id=faker.uuid4(), status="available", metadata={"automatic_snapshots": "true"}
    )
    now = datetime.datetime(2021, 6, 15, 12, 0, 0, 0, datetime.timezone.utc)
    snapshots = [
        FakeSnapshot(
            id=faker.uuid4(),
            status="available",
            volume_id=volume.id,
            metadata={},
            created_at=faker.date_time_this_century().isoformat(),
        )
        for i in range(faker.random_int(max=10))
    ]

    os_client = mocker.MagicMock()
    if last_snapshot == "last_year":
        snapshots.append(
            FakeSnapshot(
                id=faker.uuid4(),
                status="available",
                volume_id=volume.id,
                metadata={"expire_at": faker.date_this_year().isoformat()},
                created_at=(now + relativedelta(years=-1)).isoformat(),
            )
        )
    elif last_snapshot == "in_year":
        snapshots.append(
            FakeSnapshot(
                id=faker.uuid4(),
                status="available",
                volume_id=volume.id,
                metadata={"expire_at": faker.date_this_year().isoformat()},
                created_at=(now + relativedelta(months=-3)).isoformat(),
            )
        )
    elif last_snapshot == "in_month":
        snapshots.append(
            FakeSnapshot(
                id=faker.uuid4(),
                status="available",
                volume_id=volume.id,
                metadata={"expire_at": faker.date_this_year().isoformat()},
                created_at=(now + relativedelta(days=-3)).isoformat(),
            )
        )
    elif last_snapshot == "in_day":
        snapshots.append(
            FakeSnapshot(
                id=faker.uuid4(),
                status="available",
                volume_id=volume.id,
                metadata={"expire_at": faker.date_this_year().isoformat()},
                created_at=(now + relativedelta(hours=-3)).isoformat(),
            )
        )
    os_client.block_storage.snapshots.return_value = snapshots
    time_machine.move_to(now)

    cinder_snapshooter.snapshot_creator.create_snapshot_if_needed(
        volume, os_client, all_projects, dry_run
    )
    os_client.block_storage.snapshots.assert_called_once_with(
        all_projects=all_projects,
        status="available",
        volume_id=volume.id,
    )
    if dry_run or last_snapshot == "in_day":
        os_client.block_storage.create_snapshot.assert_not_called()
        return

    if last_snapshot == "in_month":
        expire_at = now + relativedelta(days=+7)
    else:
        expire_at = now + relativedelta(months=+3)
    os_client.block_storage.create_snapshot.assert_called_once_with(
        volume_id=volume.id,
        is_forced=True,
        description="Automatic daily snapshot",
        metadata={"expire_at": expire_at.date().isoformat()},
    )
