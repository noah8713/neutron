# Copyright 2014 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

"""havana_initial

Revision ID: havana
Revises: None

"""

# revision identifiers, used by Alembic.
revision = 'havana'
down_revision = None

from alembic import op
import sqlalchemy as sa


from neutron.db.migration.alembic_migrations import agent_init_ops
from neutron.db.migration.alembic_migrations import brocade_init_ops
from neutron.db.migration.alembic_migrations import cisco_init_ops
from neutron.db.migration.alembic_migrations import core_init_ops
from neutron.db.migration.alembic_migrations import firewall_init_ops
from neutron.db.migration.alembic_migrations import l3_init_ops
from neutron.db.migration.alembic_migrations import lb_init_ops
from neutron.db.migration.alembic_migrations import loadbalancer_init_ops
from neutron.db.migration.alembic_migrations import metering_init_ops
from neutron.db.migration.alembic_migrations import ml2_init_ops
from neutron.db.migration.alembic_migrations import mlnx_init_ops
from neutron.db.migration.alembic_migrations import nec_init_ops
from neutron.db.migration.alembic_migrations import other_extensions_init_ops
from neutron.db.migration.alembic_migrations import other_plugins_init_ops
from neutron.db.migration.alembic_migrations import ovs_init_ops
from neutron.db.migration.alembic_migrations import portsec_init_ops
from neutron.db.migration.alembic_migrations import ryu_init_ops
from neutron.db.migration.alembic_migrations import secgroup_init_ops
from neutron.db.migration.alembic_migrations import vmware_init_ops
from neutron.db.migration.alembic_migrations import vpn_init_ops


def upgrade():
    agent_init_ops.upgrade()
    core_init_ops.upgrade()
    l3_init_ops.upgrade()
    secgroup_init_ops.upgrade()
    portsec_init_ops.upgrade()
    other_extensions_init_ops.upgrade()
    lb_init_ops.upgrade()
    ovs_init_ops.upgrade()
    ml2_init_ops.upgrade()
    firewall_init_ops.upgrade()
    loadbalancer_init_ops.upgrade()
    vpn_init_ops.upgrade()
    metering_init_ops.upgrade()
    brocade_init_ops.upgrade()
    cisco_init_ops.upgrade()
    mlnx_init_ops.upgrade()
    nec_init_ops.upgrade()
    other_plugins_init_ops.upgrade()
    ryu_init_ops.upgrade()
    vmware_init_ops.upgrade()
    op.create_table(
        'ssl_certificates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('certificate', sa.String(length=20480), nullable=False),
        sa.Column('passphrase', sa.String(length=255), nullable=True),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'ssl_cert_chains',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('cert_chain', sa.String(length=20480), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'ssl_cert_keys',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('key', sa.String(length=20480), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'vip_ssl_cert_associations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('vip_id', sa.String(length=36), nullable=False),
        sa.Column('cert_id', sa.String(length=36), nullable=False),
        sa.Column('cert_chain_id', sa.String(length=36), nullable=True),
        sa.Column('key_id', sa.String(length=36), nullable=False),
        sa.Column('device_ip', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True),
        sa.Column('status_description', sa.String(length=255), nullable=True),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['vip_id'], ['vips.id']),
        sa.ForeignKeyConstraint(['cert_id'], ['ssl_certificates.id']),
        sa.ForeignKeyConstraint(['cert_chain_id'], ['ssl_cert_chains.id']),
        sa.ForeignKeyConstraint(['key_id'], ['ssl_cert_keys.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'ssl_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('cert_id', sa.String(length=36), nullable=False),
        sa.Column('cert_chain_id', sa.String(length=36), nullable=True),
        sa.Column('key_id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('shared', sa.Boolean, nullable=False, default=False),
        sa.ForeignKeyConstraint(['cert_id'], ['ssl_certificates.id']),
        sa.ForeignKeyConstraint(['cert_chain_id'], ['ssl_cert_chains.id']),
        sa.ForeignKeyConstraint(['key_id'], ['ssl_cert_keys.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Refactor existing vip-ssl associations to remove the
    # vip_ssl_cert_associations table as it currently is
    # and recreate it differently.
    op.drop_table('vip_ssl_cert_associations')
    op.create_table(
        'vip_ssl_cert_associations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('vip_id', sa.String(length=36), nullable=False),
        sa.Column('ssl_profile_id', sa.String(length=36), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True),
        sa.Column('status_description', sa.String(length=255), nullable=True),
        sa.Column('device_ip', sa.String(length=255), nullable=True),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['vip_id'], ['vips.id']),
        sa.ForeignKeyConstraint(['ssl_profile_id'], ['ssl_profiles.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.alter_column('pools', 'lb_method',
                    type_=sa.Enum("ROUND_ROBIN",
                                  "LEAST_CONNECTIONS",
                                  "LEAST_SESSIONS",
                                  "SOURCE_IP"),
                    existing_nullable=False)



def downgrade():
    vmware_init_ops.downgrade()
    ryu_init_ops.downgrade()
    other_plugins_init_ops.downgrade()
    nec_init_ops.downgrade()
    mlnx_init_ops.downgrade()
    cisco_init_ops.downgrade()
    brocade_init_ops.downgrade()
    metering_init_ops.downgrade()
    vpn_init_ops.downgrade()
    loadbalancer_init_ops.downgrade()
    firewall_init_ops.downgrade()
    ovs_init_ops.downgrade()
    ml2_init_ops.downgrade()
    lb_init_ops.downgrade()
    other_extensions_init_ops.downgrade()
    portsec_init_ops.downgrade()
    secgroup_init_ops.downgrade()
    l3_init_ops.downgrade()
    core_init_ops.downgrade()
    agent_init_ops.downgrade()

    op.alter_column('pools', 'lb_method',
                    type_=sa.Enum("ROUND_ROBIN",
                                  "LEAST_CONNECTIONS",
                                  "SOURCE_IP"),
                    existing_nullable=False)

    op.drop_table('vip_ssl_cert_associations')
    op.drop_table('ssl_profiles')

    op.create_table(
        'vip_ssl_cert_associations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('vip_id', sa.String(length=36), nullable=False),
        sa.Column('cert_id', sa.String(length=36), nullable=False),
        sa.Column('cert_chain_id', sa.String(length=36), nullable=True),
        sa.Column('key_id', sa.String(length=36), nullable=False),
        sa.Column('device_ip', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True),
        sa.Column('status_description', sa.String(length=255), nullable=True),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['vip_id'], ['vips.id']),
        sa.ForeignKeyConstraint(['cert_id'], ['ssl_certificates.id']),
        sa.ForeignKeyConstraint(['cert_chain_id'], ['ssl_cert_chains.id']),
        sa.ForeignKeyConstraint(['key_id'], ['ssl_cert_keys.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.drop_table('vip_ssl_cert_associations')
    op.drop_table('ssl_certificates')
    op.drop_table('ssl_cert_chains')
    op.drop_table('ssl_cert_keys')
