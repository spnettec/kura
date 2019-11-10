package org.eclipse.kura.web.client.ui;

import org.gwtbootstrap3.client.ui.base.AbstractListItem;
import org.gwtbootstrap3.client.ui.base.HasBadge;
import org.gwtbootstrap3.client.ui.base.HasDataToggle;
import org.gwtbootstrap3.client.ui.base.HasHref;
import org.gwtbootstrap3.client.ui.base.HasIcon;
import org.gwtbootstrap3.client.ui.base.HasIconPosition;
import org.gwtbootstrap3.client.ui.base.HasTarget;
import org.gwtbootstrap3.client.ui.base.HasTargetHistoryToken;
import org.gwtbootstrap3.client.ui.constants.BadgePosition;
import org.gwtbootstrap3.client.ui.constants.IconFlip;
import org.gwtbootstrap3.client.ui.constants.IconPosition;
import org.gwtbootstrap3.client.ui.constants.IconRotate;
import org.gwtbootstrap3.client.ui.constants.IconSize;
import org.gwtbootstrap3.client.ui.constants.IconType;
import org.gwtbootstrap3.client.ui.constants.Toggle;

import com.google.gwt.dom.client.Element;
import com.google.gwt.event.dom.client.ClickEvent;
import com.google.gwt.event.dom.client.ClickHandler;
import com.google.gwt.event.dom.client.HasClickHandlers;
import com.google.gwt.event.shared.HandlerRegistration;
import com.google.gwt.user.client.ui.Focusable;
import com.google.gwt.user.client.ui.HasText;

public class KuraAnchorListItem extends AbstractListItem implements HasHref, HasTargetHistoryToken, HasClickHandlers,
        Focusable, HasDataToggle, HasIcon, HasIconPosition, HasBadge, HasTarget, HasText {

    protected final KuraAnchor anchor;

    public KuraAnchorListItem() {
        anchor = new KuraAnchor();
        anchor.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                delegateEvent(KuraAnchorListItem.this, event);
            }
        });
        add(anchor, (Element) getElement());
    }

    private String data = "";

    public KuraAnchorListItem(final String text) {
        this(text, text);
    }

    public KuraAnchorListItem(final String text, String data) {
        this();
        setData(data);
    }

    public void setData(final String data) {
        anchor.setData(data);
    }

    public String getData() {
        return this.data;
    }

    @Override
    public void setText(final String text) {
        anchor.setText(text);
    }

    @Override
    public String getText() {
        return anchor.getText();
    }

    /** {@inheritDoc} */
    @Override
    public HandlerRegistration addClickHandler(final ClickHandler handler) {
        return anchor.addHandler(handler, ClickEvent.getType());
    }

    /** {@inheritDoc} */
    @Override
    public BadgePosition getBadgePosition() {
        return anchor.getBadgePosition();
    }

    /** {@inheritDoc} */
    @Override
    public String getBadgeText() {
        return anchor.getBadgeText();
    }

    /** {@inheritDoc} */
    @Override
    public Toggle getDataToggle() {
        return anchor.getDataToggle();
    }

    /** {@inheritDoc} */
    @Override
    public String getHref() {
        return anchor.getHref();
    }

    /** {@inheritDoc} */
    @Override
    public IconType getIcon() {
        return anchor.getIcon();
    }

    /** {@inheritDoc} */
    @Override
    public IconFlip getIconFlip() {
        return anchor.getIconFlip();
    }

    /** {@inheritDoc} */
    @Override
    public IconPosition getIconPosition() {
        return anchor.getIconPosition();
    }

    /** {@inheritDoc} */
    @Override
    public IconRotate getIconRotate() {
        return anchor.getIconRotate();
    }

    /** {@inheritDoc} */
    @Override
    public IconSize getIconSize() {
        return anchor.getIconSize();
    }

    /** {@inheritDoc} */
    @Override
    public int getTabIndex() {
        return anchor.getTabIndex();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public String getTarget() {
        return anchor.getTarget();
    }

    /** {@inheritDoc} */
    @Override
    public String getTargetHistoryToken() {
        return anchor.getTargetHistoryToken();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconBordered() {
        return anchor.isIconBordered();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconFixedWidth() {
        return anchor.isIconFixedWidth();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconInverse() {
        return anchor.isIconInverse();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconPulse() {
        return anchor.isIconPulse();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconSpin() {
        return anchor.isIconSpin();
    }

    /** {@inheritDoc} */
    @Override
    public void setAccessKey(final char key) {
        anchor.setAccessKey(key);
    }

    /** {@inheritDoc} */
    @Override
    public void setBadgePosition(BadgePosition badgePosition) {
        anchor.setBadgePosition(badgePosition);
    }

    /** {@inheritDoc} */
    @Override
    public void setBadgeText(String badgeText) {
        anchor.setBadgeText(badgeText);
    }

    /** {@inheritDoc} */
    @Override
    public void setDataToggle(final Toggle toggle) {
        anchor.setDataToggle(toggle);
    }

    /** {@inheritDoc} */
    @Override
    public void setEnabled(final boolean enabled) {
        super.setEnabled(enabled);
        anchor.setEnabled(enabled);
    }

    /** {@inheritDoc} */
    @Override
    public void setFocus(final boolean focused) {
        anchor.setFocus(focused);
    }

    /** {@inheritDoc} */
    @Override
    public void setHref(final String href) {
        anchor.setHref(href);
    }

    /** {@inheritDoc} */
    @Override
    public void setIcon(final IconType iconType) {
        anchor.setIcon(iconType);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconBordered(final boolean iconBordered) {
        anchor.setIconBordered(iconBordered);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconColor(String iconColor) {
        anchor.setIconColor(iconColor);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconFixedWidth(final boolean iconFixedWidth) {
        anchor.setIconFixedWidth(iconFixedWidth);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconFlip(final IconFlip iconFlip) {
        anchor.setIconFlip(iconFlip);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconInverse(final boolean iconInverse) {
        anchor.setIconInverse(iconInverse);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconPosition(final IconPosition iconPosition) {
        anchor.setIconPosition(iconPosition);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconPulse(boolean iconPulse) {
        anchor.setIconPulse(iconPulse);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconRotate(final IconRotate iconRotate) {
        anchor.setIconRotate(iconRotate);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconSize(final IconSize iconSize) {
        anchor.setIconSize(iconSize);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconSpin(final boolean iconSpin) {
        anchor.setIconSpin(iconSpin);
    }

    /** {@inheritDoc} */

    @Override
    public void setTabIndex(final int index) {
        anchor.setTabIndex(index);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void setTarget(final String target) {
        anchor.setTarget(target);
    }

    /** {@inheritDoc} */
    @Override
    public void setTargetHistoryToken(final String targetHistoryToken) {
        anchor.setTargetHistoryToken(targetHistoryToken);
    }
}
