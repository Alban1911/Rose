let observerObject
let observerCreationCallbacks = { idCallbacks: {}, tagCallbacks: {}, classCallbacks: {} }
let observerDeletionCallbacks = { idCallbacks: {}, tagCallbacks: {}, classCallbacks: {} }
let processedElements = new Set()
let elementIds = new WeakMap()

function observerSubscribeToElement(target, callback, callbackList) {
  function push(target, callback, observerMap) {
    let v = observerMap[target]

    if (v === undefined) {
      observerMap[target] = [callback]
    } else {
      v.push(callback)
    }
  }

  if (target[0] === '.') {
    push(target.slice(1), callback, callbackList.classCallbacks)
  } else if (target[0] === '#') {
    push(target.slice(1), callback, callbackList.idCallbacks)
  } else {
    push(target, callback, callbackList.tagCallbacks)
  }
}

export function subscribeToElementCreation(target, callback) {
  observerSubscribeToElement(target, callback, observerCreationCallbacks)
}

export function subscribeToElementDeletion(target, callback) {
  observerSubscribeToElement(target, callback, observerDeletionCallbacks)
}

function getElementId(element) {
  if (!elementIds.has(element)) {
    elementIds.set(element, `element_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`)
  }
  return elementIds.get(element)
}

function observerHandleElement(element, isNew, callbacks) {
  const elementId = getElementId(element)
  
  if (processedElements.has(elementId)) {
    return
  }
  
  processedElements.add(elementId)

  if (element.id != "") {
    const cb = callbacks.idCallbacks[element.id]
    if (cb != undefined) {
      for (const obj of cb) {
        try {
          obj(element)
        } catch (error) {
          console.error('Error in creation callback for id', element.id, error)
        }
      }
    }
  }

  const tagLowered = element.tagName.toLowerCase()
  const cb = callbacks.tagCallbacks[tagLowered]
  if (cb != undefined) {
    for (const obj of cb) {
      try {
        obj(element)
      } catch (error) {
        console.error('Error in creation callback for tag', tagLowered, error)
      }
    }
  }

  const classList = element.classList
  if (classList) {
    for (const nodeClass of classList) {
      const classLowered = nodeClass.toLowerCase()
      const cb = callbacks.classCallbacks[classLowered]
      if (cb != undefined) {
        for (const obj of cb) {
          try {
            obj(element)
          } catch (error) {
            console.error('Error in creation callback for class', classLowered, error)
          }
        }
      }
    }
  }

  if (isNew) {
    for (const child of element.children) {
      observerHandleElement(child, isNew, callbacks)
    }

    if (element.shadowRoot != null) {
      for (const child of element.shadowRoot.children) {
        observerHandleElement(child, isNew, callbacks)
      }

      observerObject.observe(element.shadowRoot, { attributes: false, childList: true, subtree: true })
    }
  }
}

function observerCallback(mutationsList) {
  for (const mutation of mutationsList) {
    for (const node of mutation.addedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        observerHandleElement(node, true, observerCreationCallbacks)
      }
    }

    for (const node of mutation.removedNodes) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        const elementId = elementIds.get(node)
        if (elementId) {
          processedElements.delete(elementId)
          elementIds.delete(node)
        }
        observerHandleElement(node, false, observerDeletionCallbacks)
      }
    }
  }
}

function periodicElementCheck() {
  const currentElements = Array.from(document.querySelectorAll('*'))
  const newProcessedElements = new Set()
  
  for (const element of currentElements) {
    const elementId = getElementId(element)
    if (processedElements.has(elementId)) {
      newProcessedElements.add(elementId)
    } else {
      observerHandleElement(element, true, observerCreationCallbacks)
      newProcessedElements.add(getElementId(element))
    }
  }
  
  processedElements = newProcessedElements
}

function initializeObserver() {
  if (observerObject) {
    observerObject.disconnect()
  }

  observerObject = new MutationObserver(observerCallback)
  observerObject.observe(document, { attributes: false, childList: true, subtree: true })

  const allElements = document.querySelectorAll('*')
  for (const element of allElements) {
    observerHandleElement(element, true, observerCreationCallbacks)
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeObserver)
} else {
  initializeObserver()
}

setInterval(periodicElementCheck, 5000)