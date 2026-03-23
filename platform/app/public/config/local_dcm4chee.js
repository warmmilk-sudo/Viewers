(function () {
  var language = 'zh-CN';
  var translations = {
    'OHIF Viewer is for investigational use only': 'OHIF Viewer 仅供研究使用',
    'OHIF Viewer is': 'OHIF Viewer',
    'for investigational use only': '仅供研究使用',
    'Learn more about OHIF Viewer': '了解更多 OHIF Viewer 信息',
    'Confirm and hide': '确认并隐藏',
    Upload: '上传',
    Studies: '检查',
    'Start Date': '开始日期',
    'End Date': '结束日期',
    'Accession #': '申请号'
  };
  var observerStarted = false;

  function translate(value) {
    if (!value) {
      return null;
    }

    var normalized = value.trim();
    return translations[normalized] || null;
  }

  function patchTextNode(node) {
    var translated = translate(node.nodeValue);

    if (!translated || node.nodeValue.trim() === translated) {
      return;
    }

    var leading = node.nodeValue.match(/^\s*/)[0];
    var trailing = node.nodeValue.match(/\s*$/)[0];
    node.nodeValue = leading + translated + trailing;
  }

  function patchElement(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return;
    }

    ['placeholder', 'aria-label', 'title'].forEach(function (attr) {
      var current = element.getAttribute(attr);
      var translated = translate(current);

      if (translated && current !== translated) {
        element.setAttribute(attr, translated);
      }
    });

    if (element.childNodes.length === 1 && element.firstChild.nodeType === Node.TEXT_NODE) {
      patchTextNode(element.firstChild);
    }
  }

  function applyTranslations(root) {
    var target = root;

    if (!target) {
      return;
    }

    if (target.nodeType === Node.TEXT_NODE) {
      patchTextNode(target);
      return;
    }

    if (target === document) {
      target = document.body;
    }

    if (!target || target.nodeType !== Node.ELEMENT_NODE) {
      return;
    }

    patchElement(target);

    var elements = target.querySelectorAll('*');
    for (var i = 0; i < elements.length; i += 1) {
      patchElement(elements[i]);
    }

    var walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
    var textNode;

    while ((textNode = walker.nextNode())) {
      patchTextNode(textNode);
    }
  }

  function startObserver() {
    if (observerStarted || !document.documentElement) {
      return;
    }

    observerStarted = true;
    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        if (mutation.type === 'attributes') {
          patchElement(mutation.target);
          return;
        }

        for (var i = 0; i < mutation.addedNodes.length; i += 1) {
          applyTranslations(mutation.addedNodes[i]);
        }
      });
    }).observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['placeholder', 'aria-label', 'title']
    });
  }

  try {
    document.documentElement.lang = language;

    if (window.localStorage) {
      window.localStorage.setItem('i18nextLng', language);
    }

    document.cookie = 'i18next=' + encodeURIComponent(language) + '; path=/; max-age=31536000; SameSite=Lax';
  } catch (error) {
    // Ignore storage access failures and let OHIF fall back to browser detection.
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      applyTranslations(document);
      startObserver();
    });
  } else {
    applyTranslations(document);
    startObserver();
  }
})();

window.config = {
  routerBasename: '/',
  extensions: [],
  modes: [],
  customizationService: {},
  showStudyList: true,
  maxNumberOfWebWorkers: 3,
  showLoadingIndicator: true,
  investigationalUseDialog: {
    option: 'never',
  },
  whiteLabeling: {
    createLogoComponentFn: function (React) {
      return React.createElement(
        'div',
        {
          className: 'text-primary-light text-xl font-semibold',
          style: { letterSpacing: '0.12em' },
        },
        'Hygea'
      );
    },
  },
  dataSources: [
    {
      friendlyName: 'DCM4CHEE Server',
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        name: 'dcm4chee',
        wadoUriRoot: '/dcm4chee-arc/aets/DCM4CHEE/wado',
        qidoRoot: '/dcm4chee-arc/aets/DCM4CHEE/rs',
        wadoRoot: '/dcm4chee-arc/aets/DCM4CHEE/rs',
        qidoSupportsIncludeField: true,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: true,
        supportsWildcard: true,
        dicomUploadEnabled: true,
        omitQuotationForMultipartRequest: true,
      },
    },
  ],
  defaultDataSourceName: 'dicomweb',
};
