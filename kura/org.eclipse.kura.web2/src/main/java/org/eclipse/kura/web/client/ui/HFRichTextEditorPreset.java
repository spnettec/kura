package org.eclipse.kura.web.client.ui;

import java.util.HashMap;
import java.util.Map;

@SuppressWarnings("unchecked")
public class HFRichTextEditorPreset {

    @SuppressWarnings("rawtypes")
    public static Map PRESET_VERSION3_BASIC = new HashMap();
    @SuppressWarnings("rawtypes")
    public static Map PRESET_VERSION3_ADVANCED = new HashMap();
    @SuppressWarnings("rawtypes")
    public static Map PRESET_VERSION4_COMMON = new HashMap();
    @SuppressWarnings("rawtypes")
    public static Map PRESET_VERSION4_BASIC = new HashMap();
    @SuppressWarnings("rawtypes")
    public static Map PRESET_VERSION4_ADVANCED = new HashMap();

    static {
        PRESET_VERSION3_BASIC.put("theme", "simple");
        PRESET_VERSION3_ADVANCED.put("theme", "advanced");
        PRESET_VERSION3_ADVANCED.put("theme_advanced_resizing", true);
        PRESET_VERSION3_ADVANCED.put("theme_advanced_resize_horizontal", true);
        PRESET_VERSION3_ADVANCED.put("theme_advanced_resize_vertical", true);

        PRESET_VERSION4_COMMON.put("theme", "modern");
        PRESET_VERSION4_COMMON.put("plugins",
                "textcolor codesample advlist autolink lists link image charmap preview anchor searchreplace visualblocks code insertdatetime table contextmenu paste tabfocus");
        PRESET_VERSION4_COMMON.put("browser_spellcheck", true);
        PRESET_VERSION4_COMMON.put("forced_root_block", false);
        PRESET_VERSION4_COMMON.put("force_p_newlines", false);
        PRESET_VERSION4_COMMON.put("force_br_newlines", true);
        PRESET_VERSION4_COMMON.put("setup", "hfrichtexteditorSetupCallback");
        PRESET_VERSION4_COMMON.put("init_instance_callback", "hfrichtexteditorInitCallback");

        PRESET_VERSION4_BASIC.putAll(PRESET_VERSION4_COMMON);
        PRESET_VERSION4_BASIC.put("toolbar", false);
        PRESET_VERSION4_BASIC.put("menubar", false);
        PRESET_VERSION4_BASIC.put("statusbar", false);

        PRESET_VERSION4_ADVANCED.putAll(PRESET_VERSION4_COMMON);
        PRESET_VERSION4_ADVANCED.put("menubar", "edit insert view format table tools");
        PRESET_VERSION4_ADVANCED.put("toolbar",
                "undo redo | styleselect | bold italic | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | link image");
    }

    private HFRichTextEditorPreset() {
    }

    @SuppressWarnings("rawtypes")
    public static Map getBasicOptions() {
        if (HFRichTextEditor.libraryVersion == HFRichTextEditor.TINYMCE_VERSION_3) {
            return PRESET_VERSION3_BASIC;
        } else if (HFRichTextEditor.libraryVersion == HFRichTextEditor.TINYMCE_VERSION_4) {
            return PRESET_VERSION4_BASIC;
        }
        return new HashMap();
    }

    @SuppressWarnings("rawtypes")
    public static Map getAdvancedOptions() {
        if (HFRichTextEditor.libraryVersion == HFRichTextEditor.TINYMCE_VERSION_3) {
            return PRESET_VERSION3_ADVANCED;
        } else if (HFRichTextEditor.libraryVersion == HFRichTextEditor.TINYMCE_VERSION_4) {
            return PRESET_VERSION4_ADVANCED;
        }
        return new HashMap();
    }
}
