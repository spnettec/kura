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
        this.anchor = new KuraAnchor();
        this.anchor.addClickHandler(new ClickHandler() {

            @Override
            public void onClick(ClickEvent event) {
                delegateEvent(KuraAnchorListItem.this, event);
            }
        });
        add(this.anchor, (Element) getElement());
    }

    private final String data = "";

    public KuraAnchorListItem(final String text) {
        this(text, text);
    }

    public KuraAnchorListItem(final String text, String data) {
        this();
        setData(data);
    }

    public void setData(final String data) {
        this.anchor.setData(data);
    }

    public String getData() {
        return this.data;
    }

    @Override
    public void setText(final String text) {
        this.anchor.setText(text);
    }

    @Override
    public String getText() {
        return this.anchor.getText();
    }

    /** {@inheritDoc} */
    @Override
    public HandlerRegistration addClickHandler(final ClickHandler handler) {
        return this.anchor.addHandler(handler, ClickEvent.getType());
    }

    /** {@inheritDoc} */
    @Override
    public BadgePosition getBadgePosition() {
        return this.anchor.getBadgePosition();
    }

    /** {@inheritDoc} */
    @Override
    public String getBadgeText() {
        return this.anchor.getBadgeText();
    }

    /** {@inheritDoc} */
    @Override
    public Toggle getDataToggle() {
        return this.anchor.getDataToggle();
    }

    /** {@inheritDoc} */
    @Override
    public String getHref() {
        return this.anchor.getHref();
    }

    /** {@inheritDoc} */
    @Override
    public IconType getIcon() {
        return this.anchor.getIcon();
    }

    /** {@inheritDoc} */
    @Override
    public IconFlip getIconFlip() {
        return this.anchor.getIconFlip();
    }

    /** {@inheritDoc} */
    @Override
    public IconPosition getIconPosition() {
        return this.anchor.getIconPosition();
    }

    /** {@inheritDoc} */
    @Override
    public IconRotate getIconRotate() {
        return this.anchor.getIconRotate();
    }

    /** {@inheritDoc} */
    @Override
    public IconSize getIconSize() {
        return this.anchor.getIconSize();
    }

    /** {@inheritDoc} */
    @Override
    public int getTabIndex() {
        return this.anchor.getTabIndex();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public String getTarget() {
        return this.anchor.getTarget();
    }

    /** {@inheritDoc} */
    @Override
    public String getTargetHistoryToken() {
        return this.anchor.getTargetHistoryToken();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconBordered() {
        return this.anchor.isIconBordered();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconFixedWidth() {
        return this.anchor.isIconFixedWidth();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconInverse() {
        return this.anchor.isIconInverse();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconPulse() {
        return this.anchor.isIconPulse();
    }

    /** {@inheritDoc} */
    @Override
    public boolean isIconSpin() {
        return this.anchor.isIconSpin();
    }

    /** {@inheritDoc} */
    @Override
    public void setAccessKey(final char key) {
        this.anchor.setAccessKey(key);
    }

    /** {@inheritDoc} */
    @Override
    public void setBadgePosition(BadgePosition badgePosition) {
        this.anchor.setBadgePosition(badgePosition);
    }

    /** {@inheritDoc} */
    @Override
    public void setBadgeText(String badgeText) {
        this.anchor.setBadgeText(badgeText);
    }

    /** {@inheritDoc} */
    @Override
    public void setDataToggle(final Toggle toggle) {
        this.anchor.setDataToggle(toggle);
    }

    /** {@inheritDoc} */
    @Override
    public void setEnabled(final boolean enabled) {
        super.setEnabled(enabled);
        this.anchor.setEnabled(enabled);
    }

    /** {@inheritDoc} */
    @Override
    public void setFocus(final boolean focused) {
        this.anchor.setFocus(focused);
    }

    /** {@inheritDoc} */
    @Override
    public void setHref(final String href) {
        this.anchor.setHref(href);
    }

    /** {@inheritDoc} */
    @Override
    public void setIcon(final IconType iconType) {
        this.anchor.setIcon(iconType);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconBordered(final boolean iconBordered) {
        this.anchor.setIconBordered(iconBordered);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconColor(String iconColor) {
        this.anchor.setIconColor(iconColor);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconFixedWidth(final boolean iconFixedWidth) {
        this.anchor.setIconFixedWidth(iconFixedWidth);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconFlip(final IconFlip iconFlip) {
        this.anchor.setIconFlip(iconFlip);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconInverse(final boolean iconInverse) {
        this.anchor.setIconInverse(iconInverse);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconPosition(final IconPosition iconPosition) {
        this.anchor.setIconPosition(iconPosition);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconPulse(boolean iconPulse) {
        this.anchor.setIconPulse(iconPulse);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconRotate(final IconRotate iconRotate) {
        this.anchor.setIconRotate(iconRotate);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconSize(final IconSize iconSize) {
        this.anchor.setIconSize(iconSize);
    }

    /** {@inheritDoc} */
    @Override
    public void setIconSpin(final boolean iconSpin) {
        this.anchor.setIconSpin(iconSpin);
    }

    /** {@inheritDoc} */

    @Override
    public void setTabIndex(final int index) {
        this.anchor.setTabIndex(index);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void setTarget(final String target) {
        this.anchor.setTarget(target);
    }

    /** {@inheritDoc} */
    @Override
    public void setTargetHistoryToken(final String targetHistoryToken) {
        this.anchor.setTargetHistoryToken(targetHistoryToken);
    }
}
