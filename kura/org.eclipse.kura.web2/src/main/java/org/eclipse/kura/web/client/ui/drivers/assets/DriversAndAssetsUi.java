/*******************************************************************************
 * Copyright (c) 2017, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.web.client.ui.drivers.assets;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;

import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.web.client.configuration.Configurations;
import org.eclipse.kura.web.client.configuration.HasConfiguration;
import org.eclipse.kura.web.client.messages.Messages;
import org.eclipse.kura.web.client.ui.AlertDialog;
import org.eclipse.kura.web.client.ui.AlertDialog.ConfirmListener;
import org.eclipse.kura.web.client.ui.KuraTextBox;
import org.eclipse.kura.web.client.ui.drivers.assets.DriversAndAssetsListUi.DriverAssetInfo;
import org.eclipse.kura.web.client.util.PidTextBox;
import org.eclipse.kura.web.shared.AssetConstants;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.eclipse.kura.web.shared.model.GwtWireComponentConfiguration;
import org.eclipse.kura.web.shared.model.GwtWireComposerStaticInfo;
import org.eclipse.kura.web.shared.model.GwtWireGraphConfiguration;
import org.gwtbootstrap3.client.ui.Button;
import org.gwtbootstrap3.client.ui.ListBox;
import org.gwtbootstrap3.client.ui.Modal;
import org.gwtbootstrap3.client.ui.TextArea;
import org.gwtbootstrap3.client.ui.TextBox;

import com.google.gwt.core.client.GWT;
import com.google.gwt.uibinder.client.UiBinder;
import com.google.gwt.uibinder.client.UiField;
import com.google.gwt.user.client.ui.Composite;
import com.google.gwt.user.client.ui.Widget;

public class DriversAndAssetsUi extends Composite implements DriversAndAssetsListUi.Listener {

    private static DriversAndAssetsUiUiBinder uiBinder = GWT.create(DriversAndAssetsUiUiBinder.class);

    interface DriversAndAssetsUiUiBinder extends UiBinder<Widget, DriversAndAssetsUi> {
    }

    private static final Messages MSGS = GWT.create(Messages.class);

    private static final String SELECT_COMPONENT = MSGS.servicesComponentFactorySelectorIdle();
    private static final String ASSET_FACTORY_PID = "org.eclipse.kura.wire.WireAsset";

    @UiField
    DriversAndAssetsListUi driverAndAssetsListUi;

    @UiField
    Button newDriverButton;
    @UiField
    Button newAssetButton;
    @UiField
    Button deleteButton;

    @UiField
    Modal newDriverModal;
    @UiField
    ListBox driverFactoriesList;
    @UiField
    PidTextBox driverPid;

    @UiField
    TextBox driverName;
    @UiField
    TextArea driverDesc;
    @UiField
    TextBox assetName;
    @UiField
    TextArea assetDesc;

    @UiField
    Button buttonNewDriverCancel;
    @UiField
    Button buttonNewDriverApply;

    @UiField
    Modal newAssetModal;
    @UiField
    PidTextBox assetPid;
    @UiField
    KuraTextBox assetDriverPid;
    @UiField
    Button buttonNewAssetCancel;
    @UiField
    Button buttonNewAssetApply;

    @UiField
    AlertDialog confirmDialog;

    private final Configurations configurations = new Configurations();

    public DriversAndAssetsUi() {
        initWidget(uiBinder.createAndBindUi(this));

        initButtonBar();
        initNewDriverModal();
        initNewAssetModal();

        this.driverAndAssetsListUi.setConfigurations(this.configurations);
        this.driverAndAssetsListUi.setListener(this);
    }

    public void refresh() {
        this.configurations.clear();
        DriversAndAssetsRPC.loadWireGraph(result -> {
            final GwtWireComposerStaticInfo staticInfo = result.getStaticInfo();

            this.configurations.setChannelDescriptiors(staticInfo.getDriverDescriptors());
            this.configurations.setBaseChannelDescriptor(staticInfo.getBaseChannelDescriptor());
            this.configurations.setComponentDefinitions(staticInfo.getComponentDefinitions());

            final GwtWireGraphConfiguration wireConfigurations = result.getWireGraphConfiguration();

            final List<GwtConfigComponent> configurationList = new ArrayList<>();

            for (GwtWireComponentConfiguration config : wireConfigurations.getWireComponentConfigurations()) {
                configurationList.add(config.getConfiguration());
            }

            configurationList.addAll(wireConfigurations.getAdditionalConfigurations());

            this.configurations.setComponentConfigurations(configurationList);
            this.configurations.setAllActivePids(wireConfigurations.getAllActivePids());

            init();
        });
    }

    private void init() {
        DriversAndAssetsUi.this.driverFactoriesList.clear();
        DriversAndAssetsUi.this.driverFactoriesList.addItem(SELECT_COMPONENT);
        this.configurations.getDriverFactoryPidNames().forEach((driverFactoryPid, driverFactoryName) -> {
            DriversAndAssetsUi.this.driverFactoriesList.addItem(driverFactoryName, driverFactoryPid);
        });

        clearDirtyState();
        this.driverAndAssetsListUi.refresh();
    }

    public void clearDirtyState() {
        this.driverAndAssetsListUi.setDirty(false);
    }

    public boolean isDirty() {
        return this.driverAndAssetsListUi.isDirty();
    }

    private void initButtonBar() {

        this.newDriverButton.addClickHandler(event -> {
            DriversAndAssetsUi.this.driverPid.setValue("");
            DriversAndAssetsUi.this.driverName.setValue("");
            DriversAndAssetsUi.this.driverDesc.setValue("");
            DriversAndAssetsUi.this.newDriverModal.show();
        });

        this.newAssetButton.addClickHandler(event -> {
            DriversAndAssetsUi.this.assetDriverPid.setValue(this.driverAndAssetsListUi.getSelectedItem().getName());
            DriversAndAssetsUi.this.assetDriverPid.setData(this.driverAndAssetsListUi.getSelectedItem().getPid());
            DriversAndAssetsUi.this.assetName.setValue("");
            DriversAndAssetsUi.this.assetDesc.setValue("");
            DriversAndAssetsUi.this.newAssetModal.show();
        });

        this.deleteButton.addClickHandler(event -> {
            final DriverAssetInfo info = this.driverAndAssetsListUi.getSelectedItem();

            if (info == null) {
                return;
            }

            if (info.isAsset()) {
                deleteAsset(info.getPid());
            } else {
                deleteDriver(info.getPid());
            }
        });
    }

    private void deleteComponent(final String pid) {
        DriversAndAssetsRPC.deleteFactoryConfiguration(pid, result -> {
            this.configurations.deleteConfiguration(pid);
            this.driverAndAssetsListUi.refresh();
            this.refresh();
        });
    }

    private void deleteDriver(final String pid) {

        for (HasConfiguration hasConfiguration : this.configurations.getConfigurations()) {
            final GwtConfigComponent gwtConfig = hasConfiguration.getConfiguration();
            final String configDriverPid = gwtConfig.getParameterValue(AssetConstants.ASSET_DRIVER_PROP.value());
            if (pid.equals(configDriverPid)) {
                this.confirmDialog.show(MSGS.driversAssetsDeletingDriverWithAssets(), AlertDialog.Severity.ALERT,
                        (ConfirmListener) null);
                return;
            }
        }

        this.confirmDialog.show(MSGS.driversAssetsConfirmDeleteDriver(), () -> deleteComponent(pid));
    }

    private void deleteAsset(final String pid) {
        final HasConfiguration config = this.configurations.getConfiguration(pid);
        final GwtConfigComponent gwtConfig = config.getConfiguration();

        if (gwtConfig.isWireComponent()) {
            this.confirmDialog.show(MSGS.driversAssetsAssetInComposer(), AlertDialog.Severity.ALERT,
                    (ConfirmListener) null);
            return;
        }

        this.confirmDialog.show(MSGS.driversAssetsConfirmDeleteAsset(), () -> deleteComponent(pid));
    }

    private void createAsset(final String pid, final String driverPid, String assertName, String assertDesc) {
        final HasConfiguration assetConfig = this.configurations.createConfiguration(pid, ASSET_FACTORY_PID, assertName,
                assertDesc);
        assetConfig.getConfiguration().getParameter(AssetConstants.ASSET_DRIVER_PROP.value()).setValue(driverPid);
        assetConfig.getConfiguration().set(ConfigurationService.KURA_SERVICE_NAME, assertName);
        assetConfig.getConfiguration().set(ConfigurationService.KURA_SERVICE_DESC, assertDesc);
        DriversAndAssetsRPC.createFactoryConfiguration(pid, ASSET_FACTORY_PID, assetConfig.getConfiguration(),
                result -> {
                    this.configurations.setConfiguration(assetConfig.getConfiguration());
                    this.newAssetModal.hide();
                    this.driverAndAssetsListUi.refresh();
                }, error -> {
                    this.newAssetModal.hide();
                });
    }

    private void initNewDriverModal() {
        this.buttonNewDriverApply.addClickHandler(event -> {
            String driverpPid = DriversAndAssetsUi.this.driverPid.getPid();
            final String name = DriversAndAssetsUi.this.driverName.getText();
            final String desc = DriversAndAssetsUi.this.driverDesc.getText();

            final String factoryPid = DriversAndAssetsUi.this.driverFactoriesList.getSelectedValue();
            if (driverpPid == null || driverpPid.equals("")) {
                driverpPid = factoryPid + "-" + new Date().getTime();
            }
            final String pid = driverpPid;
            if (this.driverFactoriesList.getSelectedIndex() == 0) {
                this.confirmDialog.show(MSGS.driversAssetsInvalidDriverFactory(), AlertDialog.Severity.ERROR,
                        (ConfirmListener) null);
                return;
            }

            if (this.configurations.isPidExisting(pid)) {
                this.confirmDialog.show(MSGS.wiresComponentNameAlreadyUsed(pid), AlertDialog.Severity.ERROR,
                        (ConfirmListener) null);
                return;
            }

            DriversAndAssetsRPC.createNewDriver(factoryPid, pid, name, desc, result -> {
                this.configurations.createAndRegisterConfiguration(pid, factoryPid, name, desc);
                this.configurations.setChannelDescriptor(pid, result);
                this.newDriverModal.hide();
                this.driverAndAssetsListUi.refresh();
            }, error -> {
                this.newDriverModal.hide();
            });
        });
    }

    private void initNewAssetModal() {

        this.buttonNewAssetApply.addClickHandler(event -> {
            final String inputPid = this.assetPid.getPid();
            final String name = this.assetName.getText();
            final String desc = this.assetDesc.getText();

            final String newDriverPid = this.driverAndAssetsListUi.getSelectedItem().getPid();

            String pid = inputPid;
            if (pid == null || pid.equals("")) {
                pid = newDriverPid + "-" + new Date().getTime();
            }

            if (this.configurations.isPidExisting(pid)) {
                this.confirmDialog.show(MSGS.wiresComponentNameAlreadyUsed(pid), AlertDialog.Severity.ALERT,
                        (ConfirmListener) null);
                return;
            }

            createAsset(pid, newDriverPid, name, desc);

            // reset pid textbox
            this.assetPid.setValue("");
            this.assetName.setValue("");
            this.assetDesc.setValue("");
        });
    }

    @Override
    public void onSelectionChanged(DriverAssetInfo info) {
        if (info != null) {
            this.deleteButton.setEnabled(true);
            this.newAssetButton.setEnabled(!info.isAsset() && info.isValid());
        } else {
            this.deleteButton.setEnabled(false);
            this.newAssetButton.setEnabled(false);
        }
    }

}
