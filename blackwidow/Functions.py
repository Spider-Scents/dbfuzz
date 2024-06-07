# Functions.py contains general purpose functions can be utilized by
# the crawler.

from selenium import webdriver
from selenium.webdriver.support.select import Select
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException, UnexpectedAlertPresentException, NoSuchFrameException, NoAlertPresentException, ElementNotVisibleException, InvalidElementStateException
from urllib.parse import urlparse, urljoin
import json
import pprint
import datetime
import math
import os
import traceback
import random
import re
import logging
import copy
import time
import operator

import Classes
from extractors.Events import extract_events
from extractors.Forms import extract_forms, parse_form
from extractors.Urls import extract_urls
from extractors.Iframes import extract_iframes



# From: https://stackoverflow.com/a/47298910
def send(driver, cmd, params={}):
  resource = "/session/%s/chromium/send_command_and_get_result" % driver.session_id
  url = driver.command_executor._url + resource
  body = json.dumps({'cmd': cmd, 'params': params})
  response = driver.command_executor._request('POST', url, body)
  if "status" in response:
    logging.error(response)
    #raise Exception(response.get('value'))
  #return response.get('value')

def add_script(driver, script):
  send(driver, "Page.addScriptToEvaluateOnNewDocument", {"source": script})


# Changes the address from the row to the first cell
# Only modifies if it is a table row
# In:  /html/body/table/tbody/tr[4]
# Out: /html/body/table/tbody/tr[4]/td[1]
def xpath_row_to_cell(addr):
    # It seems impossible to click (and do other actions)
    # on a <tr> (Table row).
    # Instead, the onclick applies to all cells in the row.
    # Therefore, we pick the first cell.
    parts = addr.split("/")
    if(parts[-1][:2] == "tr"):
        addr += "/td[1]"
    return addr










def remove_alerts(driver):
    # Try to clean up alerts
    try:
        alert = driver.switch_to_alert()
        alert.dismiss()
    except NoAlertPresentException:
        pass



def depth(edge):
    depth = 1
    while edge.parent:
        depth = depth + 1
        edge = edge.parent
    return depth

def dom_depth(edge):
    depth = 1
    while edge.parent and edge.value.method == "event":
        depth = depth + 1
        edge = edge.parent
    return depth

# Execute the path necessary to reach the state
def find_state(driver, graph, edge):
    path = rec_find_path(graph, edge)

    for edge_in_path in path:
        method = edge_in_path.value.method
        method_data = edge_in_path.value.method_data
        logging.info("find_state method %s" % method)

        if allow_edge(graph, edge_in_path):
            if method == "get":
                driver.get(edge_in_path.n2.value.url)
            elif method == "form":
                form = method_data
                try:
                    form_fill(driver, form)
                except Exception as e:
                    print(e)
                    print(traceback.format_exc())
                    logging.error(e)
                    return False
            elif method == "ui_form":
                ui_form = method_data
                try:
                    ui_form_fill(driver, ui_form)
                except Exception as e:
                    print(e)
                    print(traceback.format_exc())
                    logging.error(e)
                    return False
            elif method == "event":
                event = method_data
                execute_event(driver, event)
                remove_alerts(driver)
            elif method == "iframe":
                enter_status = enter_iframe(driver, method_data)
                if not enter_status:
                    logging.error("could not enter iframe (%s)" % method_data)
                    return False
            elif method == "javascript":
                # The javascript code is stored in the to-node
                # "[11:]" gives everything after "javascript:"
                js_code = edge_in_path.n2.value.url[11:]
                try:
                    driver.execute_script(js_code)
                except Exception as e:
                    print(e)
                    print(traceback.format_exc())
                    logging.error(e)
                    return False
            else:
                raise Exception( "Can't handle method (%s) in find_state" % method )

    return True


# Recursively follows parent until a stable node is found.
# Stable in this case would be defined as a GET
def rec_find_path(graph, edge):
    path = []
    method = edge.value.method
    parent = edge.parent

    # This is the base case since the first request is always get.
    if method == "get":
        return path + [edge]
    else:
        return rec_find_path(graph, parent) + [edge]


def edge_sort(edge):
    if edge.value[0] == "form":
        return 0
    else:
        return 1


# Check if we should follow edge
# Could be based on SOP, number of reqs, etc.
def check_edge(driver, graph, edge):
    logging.info("Check edge: " + str(edge) )
    method = edge.value.method
    method_data = edge.value.method_data

    # TODO use default FALSE/TRUE
    if method == "get":
        if allow_edge(graph, edge):
            purl = urlparse(edge.n2.value.url)
            if not purl.path in graph.data['urls']:
                graph.data['urls'][purl.path] = 0
            graph.data['urls'][purl.path] += 1

            if graph.data['urls'][purl.path] > 120:
                return False
            else:
                return True
        else:
            logging.warning("Not allow to get %s" % str(edge.n2.value))
            return False
    elif method == "form":
        purl = urlparse(method_data.action)
        if not purl.path in graph.data['form_urls']:
            graph.data['form_urls'][purl.path] = 0
        graph.data['form_urls'][purl.path] += 1

        if graph.data['form_urls'][purl.path] > 10:
            logging.info("FROM ACTION URL (path) %s, visited more than 10 times, mark as done" % str(edge.n2.value.url))
            return False
        else:
            return True
    elif method == "event":
        # TODO XXX REMOVE THIS
        return False
        if dom_depth(edge) > 10:
            logging.info("Dom depth (10) reached! Discard edge %s " % ( str(edge) ) )
            return False
        else:
            return True
    else:
        return True




def follow_edge(driver, graph, edge):

    logging.info("Follow edge: " + str(edge) )
    method = edge.value.method
    method_data = edge.value.method_data
    if method == "get":
        driver.get(edge.n2.value.url)
    elif method == "form":
        logging.info("Form, do find_state")
        if not find_state(driver, graph, edge):
            logging.warning("Could not find state %s" % str(edge))
            edge.visited = True
            return None
    elif method == "event":
        logging.info("Event, do find_state")
        if not find_state(driver, graph, edge):
            logging.warning("Could not find state %s" % str(edge))
            edge.visited = True
            return None
    elif method == "iframe":
        logging.info("iframe, do find_state")
        if not find_state(driver, graph, edge):
            logging.warning("Could not find state %s" % str(edge))
            edge.visited = True
            return None
    elif method == "javascript":
        logging.info("Javascript, do find_state")
        if not find_state(driver, graph, edge):
            logging.warning("Could not find state %s" % str(edge))
            edge.visited = True
            return None
    elif method == "ui_form":
        logging.info("ui_form, do find_state")
        if not find_state(driver, graph, edge):
            logging.warning("Could not find state %s" % str(edge))
            edge.visited = True
            return None
    else:
        raise Exception( "Can't handle method (%s) in next_unvisited_edge " % method )

    # Success
    return True




# Checks if two URLs target the same origin
def same_origin(u1, u2):
    p1 = urlparse(u1)
    p2 = urlparse(u2)

    return (    p1.scheme == p2.scheme
            and p1.netloc == p2.netloc )

def allow_edge(graph, edge):

    crawl_edge = edge.value

    if crawl_edge.method == "get":
        to_url = edge.n2.value.url
    elif crawl_edge.method == "form":
        to_url = crawl_edge.method_data.action
    elif crawl_edge.method == "iframe":
        to_url = crawl_edge.method_data.src
    elif crawl_edge.method == "event":
        ignore = ["onerror"] # Some events that we can't/don't trigger
        return not (crawl_edge.method_data.event in ignore)
    else:
        logging.info("Unsure about method %s, will allow." % crawl_edge.method)
        return True

    from_url = graph.nodes[1].value.url

    parsed_to_url = urlparse(to_url)

    # Relative links are fine. (Not sure about // links)
    if not parsed_to_url.scheme:
        return True

    # If the sceme is javascript we can't know to final destination, so we allow.
    if parsed_to_url.scheme == "javascript":
        return True


    so = same_origin(from_url, to_url)

    # TODO: More general solutions ? e.g regex patterns, counts etc.
    blacklisted_terms = []
    # For SCARF
    blacklisted_terms.extend( ["logout"] )
    # For WIVET
    # blacklisted_terms.extend( ["logout", "offscanpages"] )
    # For WackoPico
    # blacklisted_terms.extend( ["calendar.php"] )
    # For DVWA
    # blacklisted_terms.extend( ["setup.php"] )
    # For Drupal
    # blacklisted_terms.extend( ["logout"] )

    # blacklisted_terms.extend( ["c6ede933243c2c0f8a77e30ea3dc89c23304c9f4ef4227317f2dc8d5"] )
    # blacklisted_terms.extend( ["2ec5d2da0be59c9feaeaa264e7a1f1e5bc71183b6c0cecff340b8c3f"] )
    # blacklisted_terms.extend( ["index.php"] )



    if blacklisted_terms:
        logging.warning("Using blacklisted terms!")

    if to_url:
        bl = any([bt in to_url for bt in blacklisted_terms])
    else:
        bl = False

    # If we are in the same origin AND the request is not blacklisted
    # (Could just return (so and not bl) but this is clearer imho)
    if so and not bl:
        return True
    else:
        logging.debug("Different origins %s and %s" % (str(from_url), str(to_url)))
        return False






def execute_event(driver, do):
    logging.info("We need to trigger [" +  do.event + "] on " + do.addr)

    do.addr = xpath_row_to_cell(do.addr)

    try:
        if   do.event == "onclick" or do.event == "click":
            web_element =  driver.find_element(By.XPATH, do.addr)
            logging.info("Click on %s" % web_element )

            if web_element.is_displayed():
                web_element.click()
            else:
                logging.warning("Trying to click on invisible element. Use JavaScript")
                driver.execute_script("arguments[0].click()", web_element)
        elif do.event == "ondblclick" or do.event == "dblclick":
            web_element =  driver.find_element(By.XPATH, do.addr)
            logging.info("Double click on %s" % web_element )
            ActionChains(driver).double_click(web_element).perform()

            #if web_element.is_displayed():
            #    web_element.click()

        elif do.event == "onmouseout":
            logging.info("Mouseout on %s" %  driver.find_element(By.XPATH, do.addr) )
            driver.find_element(By.XPATH, do.addr).click()
            el = driver.find_element(By.XPATH, do.addr)
            # TODO find first element in body
            body = driver.find_element(By.XPATH, "/html/body")
            ActionChains(driver).move_to_element(el).move_to_element(body).perform()
        elif do.event == "onmouseover":
            logging.info("Mouseover on %s" %  driver.find_element(By.XPATH, do.addr) )
            el = driver.find_element(By.XPATH, do.addr)
            ActionChains(driver).move_to_element(el).perform()
        elif  do.event == "onmousedown":
            logging.info("Click (mousedown) on %s" %  driver.find_element(By.XPATH, do.addr) )
            driver.find_element(By.XPATH, do.addr).click()
        elif  do.event == "onmouseup":
            logging.info("Mouseup on %s" %  driver.find_element(By.XPATH, do.addr) )
            el = driver.find_element(By.XPATH, do.addr)
            ActionChains(driver).move_to_element(el).release().perform()
        elif  do.event == "change" or do.event == "onchange":
            el = driver.find_element(By.XPATH, do.addr)
            logging.info("Change %s" %  driver.find_element(By.XPATH, do.addr) )
            if el.tag_name == "select":
                # If need to change a select we try the different
                # options
                opts = el.find_elements("tag name", "option")
                for opt in opts:
                    try:
                        opt.click()
                    except UnexpectedAlertPresentException:
                        print("Alert detected")
                        alert = driver.switch_to_alert()
                        alert.dismiss()
            else:
                # If ot a <select> we try to write
                el = driver.find_element(By.XPATH, do.addr)
                el.clear()
                el.send_keys("jAEkPot")
                el.send_keys(Keys.RETURN)
        elif  do.event == "input" or do.event == "oninput":
            el = driver.find_element(By.XPATH, do.addr)
            el.clear()
            el.send_keys("jAEkPot")
            el.send_keys(Keys.RETURN)
            logging.info("oninput %s" %  driver.find_element(By.XPATH, do.addr) )

        elif  do.event == "compositionstart":
            el = driver.find_element(By.XPATH, do.addr)
            el.clear()
            el.send_keys("jAEkPot")
            el.send_keys(Keys.RETURN)
            logging.info("Composition Start %s" %  driver.find_element(By.XPATH, do.addr) )

        else:
            logging.warning("Warning Unhandled event %s " % str(do.event) )
    except Exception as e:
        print("Error", do)
        print(e)





def form_fill_file(filename):
    dirname = os.path.dirname(__file__)
    path = os.path.join(dirname, 'form_files', filename)

    if filename != "jaekpot.jpg":
        path = os.path.join(dirname, 'form_files', 'dynamic', filename)
        dynamic_file = open(path, "w+")
        # Could it be worth to add a file content payload?
        dynamic_file.write(filename)
        dynamic_file.close()

    return path



# The problem is that equality does not cover both cases
# Different values => Different Edges           (__eq__)
# Different values => Same form on the webpage  (fuzzy)
# Highly dependent on __eq__ for each element
def fuzzy_eq(form1, form2):
    if form1.action != form2.action:
        return False
    if form1.method != form2.method:
        return False
    for el1 in form1.inputs.keys():
        if not (el1 in form2.inputs):
            return False
    return True

def update_value_with_js(driver, web_element, new_value):
    try:
        try:
            new_value = new_value.replace("'", "\\'")
        except:
            logging.error("Could not replace quotes, maybe not string")
        driver.execute_script("arguments[0].value = '"+str(new_value)+"'", web_element)
    except Exception as e:
        logging.error(e)
        logging.error(traceback.format_exc())
        logging.error("faild to update with JS " + str(web_element)  )

def form_fill(driver, target_form):
    logging.debug("Filling "+ str(target_form))

    # Ensure we don't have any alerts before filling in form
    try:
        alert = driver.switch_to_alert()
        alertText = alert.text
        logging.info("Removed alert: " +  alertText)
        alert.accept();
    except:
        logging.info("No alert removed (probably due to there not being any)")
        pass

    elem = driver.find_elements("tag name", "form")
    for el in elem:

        current_form = parse_form(el, driver)

        submit_buttons = []

        if( not fuzzy_eq(current_form, target_form) ):
            continue

        # TODO handle each element
        inputs = el.find_elements("tag name", "input")

        if not inputs:
            inputs = []
            logging.warning("No inputs founds, falling back to JavaScript")
            resps = driver.execute_script("return get_forms()")
            js_forms = json.loads(resps)
            for js_form in js_forms:
                current_form = Classes.Form()
                current_form.method = js_form['method'];
                current_form.action = js_form['action'];

                # TODO Need better COMPARE!
                if( current_form.action == target_form.action and current_form.method ==  target_form.method ):
                    for js_el in js_form['elements']:
                        web_el = driver.find_element(By.XPATH, js_el['xpath'])
                        inputs.append(web_el)
                    break



        buttons = el.find_elements("tag name", "button")
        for button in buttons:
            # We ignore anonymous buttons that have been tagged with a fake id
            if not button.get_attribute("id").startswith("fakeid"):
                inputs.append(button)

        for iel in inputs:

            try:
                iel_type = empty2none(iel.get_attribute("type"))
                iel_name = empty2none(iel.get_attribute("name"))
                if not iel_name:
                    iel_name = empty2none(iel.get_attribute("id"))
                iel_value = empty2none(iel.get_attribute("value"))
                iel_pattern = empty2none(iel.get_attribute("pattern"))
                if iel.get_attribute("type") == "radio":
                    # RadioElement has a different equal function where value is important
                    form_iel = Classes.Form.RadioElement(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value
                                                     )
                elif iel.get_attribute("type") == "checkbox":
                    form_iel = Classes.Form.CheckboxElement(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value,
                                                     None)
                elif iel.get_attribute("type") == "submit":
                    form_iel = Classes.Form.SubmitElement(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value,
                                                     None)
                else:
                    form_iel = Classes.Form.Element(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value,
                                                     iel_pattern
                                                     )
                    logging.warning("Default handling for %s " % str(form_iel))


                if form_iel in target_form.inputs:
                    i = target_form.inputs[form_iel]

                    if iel.get_attribute("type") == "submit" or iel.get_attribute("type") == "image" or iel.get_attribute("type") == "button":
                        # print("ADDING SUBMIT, ", iel)
                        submit_buttons.append( (iel, i) )
                    elif iel.get_attribute("type") == "file":
                        if "/" in i.value:
                            logging.info("Cannot have slash in filename")
                        else:
                            try:
                                iel.send_keys( form_fill_file(i.value) )
                            except Exception as e:
                                logging.warning("[inputs] Failed to upload file " + str(i.value) + " in " + str(form_iel)  )
                    elif iel.get_attribute("type") == "radio":
                        if i.override_value:
                            update_value_with_js(driver, iel, i.override_value)
                        if i.click:
                            iel.click()
                    elif iel.get_attribute("type") == "checkbox":
                        if i.override_value:
                            update_value_with_js(driver, iel, i.override_value)
                        if i.checked and not iel.get_attribute("checked"):
                            iel.click()
                    elif iel.get_attribute("type") == "hidden":
                        print("IGNORE HIDDEN")
                        #update_value_with_js(driver, iel, i.value)
                    elif iel.get_attribute("type") in ["text", "email", "url"]:
                        if iel.get_attribute("maxlength"):
                            try:
                                driver.execute_script("arguments[0].removeAttribute('maxlength')", iel)
                            except Exception as e:
                                logging.warning("[inputs] faild to change maxlength " + str(form_iel)  )
                        try:
                            iel.clear()
                            iel.send_keys(i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            try:
                                driver.execute_script("arguments[0].value = '"+str(i.value)+"'", iel)
                            except Exception as e:
                                logging.error(e)
                                logging.error(traceback.format_exc())
                                logging.error("[inputs] also faild with JS " + str(form_iel)  )
                    elif iel.get_attribute("type") == "password":
                        try:
                            iel.clear()
                            iel.send_keys(i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)
                    elif iel.get_attribute("type") == "number" or  iel.get_attribute("type") == "range":
                        if iel.get_attribute("min"):
                            i.value = iel.get_attribute("min")
                        elif  iel.get_attribute("max"):
                            if  iel.get_attribute("step"):
                                step = int(iel.get_attribute("step"))
                                maxv = int(iel.get_attribute("max"))
                                i.value = step * math.floor(maxv/step)
                            else:
                                i.value = iel.get_attribute("max")
                        try:
                            iel.clear()
                            update_value_with_js(driver, iel, i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)
                    elif iel.get_attribute("type") == "color":
                        i.value = "#000000" # Black like the Ostrich
                        try:
                            iel.clear()
                            iel.send_keys(i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)

                    elif iel.get_attribute("type") == "date" or iel.get_attribute("type") == "datetime":
                        i.value = "03132003" # 18 years is probably good for birthdays etc
                        try:
                            iel.clear()
                            iel.send_keys(i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)
                    elif iel.get_attribute("type") == "time":
                        i.value = "01021" # 01:02 AM
                        try:
                            iel.clear()
                            iel.send_keys(i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)
                    elif iel.get_attribute("type") == "month":
                        i.value = "2003-03"
                        try:
                            iel.clear()
                            update_value_with_js(driver, iel, i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)
                    elif iel.get_attribute("type") == "week":
                        i.value = "2003-W10"
                        try:
                            iel.clear()
                            update_value_with_js(driver, iel, i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)

                    else:
                        logging.warning("[inputs] using default clear/send_keys for " + str(form_iel) )
                        try:
                            iel.clear()
                            iel.send_keys(i.value)
                        except Exception as e:
                            logging.warning("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                            update_value_with_js(driver, iel, i.value)
                else:
                    logging.warning("[inputs] could NOT FIND " + str(form_iel) )
                    logging.warning("--" + str(target_form.inputs))
                logging.info("Filling in input " + iel.get_attribute("name") )

            except Exception as e:
                logging.error("Could not fill in form")
                logging.error(e)
                logging.error(traceback.format_exc())

        # <select>
        selects = el.find_elements("tag name", "select")
        for select in selects:
            select_name = select.get_attribute("name")
            if not select_name:
                select_name = select.get_attribute("id")
            form_select = Classes.Form.SelectElement( "select", select_name)

            if form_select in target_form.inputs:
                i = target_form.inputs[form_select]
                selenium_select = Select( select )
                options = selenium_select.options
                if i.override_value and options:
                    update_value_with_js(driver, options[0], i.override_value)
                else:
                    for option in options:
                        if option.get_attribute("value") == i.selected:
                            try:
                                option.click()
                            except Exception as e:
                                logging.error("Could not click on " + str(form_select) + ", trying JS")
                                update_value_with_js(driver, select, i.selected)
                            break
            else:
                logging.warning("[selects] could NOT FIND " + str(form_select) )



        # <textarea>
        textareas = el.find_elements("tag name", "textarea")
        for ta in textareas:
            form_ta = Classes.Form.Element( ta.get_attribute("type"),
                                            ta.get_attribute("name"),
                                            ta.get_attribute("value") )
            if form_ta in target_form.inputs:
                i = target_form.inputs[form_ta]
                try:
                    ta.clear()
                    ta.send_keys(i.value)
                except Exception as e:
                    logging.info("[inputs] faild to send keys to " + str(form_iel) + " Trying javascript" )
                    update_value_with_js(driver, ta, i.value)
            else:
                logging.warning("[textareas] could NOT FIND " + str(form_ta) )

        # <iframes>
        iframes = el.find_elements("tag name", "iframe")
        for iframe in iframes:
            form_iframe = Classes.Form.Element("iframe", iframe.get_attribute("id"), "")


            if form_iframe in target_form.inputs:
                i = target_form.inputs[form_iframe]
                try:
                    iframe_id =  i.name
                    driver.switch_to.frame(iframe_id)
                    iframe_body = driver.find_element(By.TAG_NAME, "body")
                    if(iframe_body.get_attribute("contenteditable") == "true"):
                        iframe_body.clear()
                        iframe_body.send_keys(i.value)
                    else:
                        logging.error("Body not contenteditable, was during parse")

                    driver.switch_to.default_content();


                except InvalidElementStateException as e:
                    logging.error("Could not clear " + str(form_ta))
                    logging.error(e)
            else:
                logging.warning("[iframes] could NOT FIND " + str(form_ta) )


        # Double check SMT after filling in form
        for iel in inputs:
            try:
                iel_type = empty2none(iel.get_attribute("type"))
                iel_name = empty2none(iel.get_attribute("name"))
                if not iel_name:
                    iel_name = empty2none(iel.get_attribute("id"))
                iel_value = empty2none(iel.get_attribute("value"))
                iel_pattern = empty2none(iel.get_attribute("pattern"))
                if iel.get_attribute("type") == "radio":
                    # RadioElement has a different equal function where value is important
                    form_iel = Classes.Form.RadioElement(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value
                                                     )
                elif iel.get_attribute("type") == "checkbox":
                    form_iel = Classes.Form.CheckboxElement(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value,
                                                     None)
                elif iel.get_attribute("type") == "submit":
                    form_iel = Classes.Form.SubmitElement(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value,
                                                     None)
                else:
                    form_iel = Classes.Form.Element(
                                                     iel_type,
                                                     iel_name,
                                                     iel_value,
                                                     iel_pattern
                                                     )
                    logging.warning("Default handling for %s " % str(form_iel))



            except:
                pass


        # submit
        if submit_buttons:
            logging.info("form_fill Clicking on submit button")

            for submit_button in submit_buttons:
                (selenium_submit, form_submit) = submit_button

                if form_submit.use:
                    try:
                        selenium_submit.click()
                        # Clicking the submit can trigger an onChange event on another element.
                        # This will cause the submission to fail.
                        # So to be sure, we try to click again.
                        try:
                            selenium_submit.click()
                        except:
                            pass
                        break
                    except ElementNotVisibleException as e:
                        logging.warning("Cannot click on invisible submit button: " + str(submit_button) + str(target_form) + " trying JavaScript click")
                        logging.info("form_fill Javascript submission of form after failed submit button click")

                        driver.execute_script("arguments[0].click()", selenium_submit)

                        # Also try submitting the full form, shouldn't be needed
                        try:
                            el.submit()
                        except Exception as e:
                            logging.info("Could not submit form, could be good!")

                    except Exception as e:
                        logging.warning("Cannot click on submit button: " + str(submit_button) + str(target_form))
                        logging.info("form_fill Javascript submission of form after failed submit button click")
                        el.submit()

                # Some forms show an alert with a confirmation
                try:
                    alert = driver.switch_to_alert()
                    alertText = alert.text
                    logging.info("Removed alert: " +  alertText)
                    alert.accept();
                except:
                    logging.info("No alert removed (probably due to there not being any)")
                    pass
        else:
            logging.info("form_fill Javascript submission of form")
            el.submit()


        # Check if submission caused an "are you sure" alert
        try:
            alert = driver.switch_to_alert()
            alertText = alert.text
            logging.info("Removed alert: " +  alertText)
            alert.accept();
        except:
            logging.info("No alert removed (probably due to there not being any)")

        # End of form fill if everything went well
        return True

    logging.error("error no form found (url:%s, form:%s)" % (driver.current_url, target_form) )
    return False
    #raise Exception("error no form found (url:%s, form:%s)" % (driver.current_url, target_form) )


def ui_form_fill(driver, target_form):
    logging.debug("Filling ui_form "+ str(target_form))

    # Ensure we don't have any alerts before filling in form
    try:
        alert = driver.switch_to_alert()
        alertText = alert.text
        logging.info("Removed alert: " +  alertText)
        alert.accept();
    except:
        logging.info("No alert removed (probably due to there not being any)")
        pass


    for source in target_form.sources:
        web_element =  driver.find_element(By.XPATH, source['xpath'])

        if web_element.get_attribute("maxlength"):
            try:
                driver.execute_script("arguments[0].removeAttribute('maxlength')", web_element)
            except Exception as e:
                logging.warning("[inputs] faild to change maxlength " + str(web_element)  )

        input_value = source['value']
        try:
            web_element.clear()
            web_element.send_keys(input_value)
        except Exception as e:
            logging.warning("[inputs] faild to send keys to " + str(input_value) + " Trying javascript" )
            try:
                driver.execute_script("arguments[0].value = '"+input_value+"'", web_element)
            except Exception as e:
                logging.error(e)
                logging.error(traceback.format_exc())
                logging.error("[inputs] also faild with JS " + str(web_element)  )


    submit_element =  driver.find_element(By.XPATH, target_form.submit)
    submit_element.click()

def set_standard_values(old_form):
    form = copy.deepcopy(old_form)
    first_radio = True


    for form_el in form.inputs.values():

        if form_el.itype == "file":
            form_el.value = "jaekpot.jpg"
        elif form_el.itype == "radio":
            if first_radio:
                form_el.click = True
                first_radio = False
            # else dont change the value
        elif form_el.itype == "checkbox":
            # Just activate all checkboxes
            form_el.checked = True
        elif form_el.itype == "submit" or form_el.itype == "image":
            form_el.use = False
        elif form_el.itype == "select":
            if form_el.options:
                form_el.selected = form_el.options[0]
                if not form_el.selected:
                    # print("empty pick next")
                    form_el.selected = form_el.options[1]

            else:
                logging.warning( str(form_el) + " has no options" )
        elif form_el.itype == "text":
            if form_el.value and form_el.value.isdigit():
                form_el.value = 1
            elif form_el.name == "email":
                form_el.value = "jaekpot@localhost.com"
            else:
                form_el.value = "jAEkPot"



        elif form_el.itype == "textarea":
            form_el.value = "jAEkPot"
        elif form_el.itype == "email":
            form_el.value = "admin@alex.example"
        elif form_el.itype == "hidden":
            pass
        elif form_el.itype == "password":
            form_el.value = "jAEkPot"
            #form_el.value = "jAEkPot1"
        elif form_el.itype == "number":
            # TODO Look at min/max/step/maxlength to pick valid numbers
            form_el.value = "1"
        elif form_el.itype == "iframe":
            form_el.value = "jAEkPot"
        elif form_el.itype == "button":
            pass
        else:
            logging.warning( str(form_el) + " was handled by default")
            form_el.value = "jAEkPot"

    return form

def set_submits(forms):
    new_forms = set()
    for form in forms:
        submits = set()
        for form_el in form.inputs.values():
            if form_el.itype == "submit" or form_el.itype == "image" or form_el.itype == "button":
                submits.add(form_el)

        if len(submits) > 1:
            for submit in submits:
                new_form = copy.deepcopy(form)
                for new_form_el in new_form.inputs.values():
                    if new_form_el.itype == "submit" and new_form_el == submit:
                        new_form_el.use = True

                new_forms.add(new_form)
        elif len(submits) == 1:
            submits.pop().use = True
            new_forms.add(form)

    return new_forms

def set_checkboxes(forms):
    new_forms = set()
    for form in forms:
        new_form = copy.deepcopy(form)
        for new_form_el in new_form.inputs.values():
            if new_form_el.itype == "checkbox":
                new_form_el.checked = False
                new_forms.add(form)
                new_forms.add(new_form)
    return new_forms

def set_form_values(forms):
    logging.info("set_form_values got " + str(len(forms)))
    new_forms = set()
    # Set values for forms.
    # Could also create copies of forms to test different values
    for old_form in forms:
        new_forms.add( set_standard_values(old_form) )


    # Handle submits
    #forms = copy.deepcopy( new_forms )
    new_forms = set_submits(new_forms)

    # Checkboxes
    new_checkbox_forms = set_checkboxes(new_forms)
    for checkbox_form in new_checkbox_forms:
        new_forms.add(checkbox_form)


    logging.info("set_form_values returned " + str(len(new_forms)))

    return new_forms


def enter_iframe(driver, target_frame):
    elem = driver.find_elements("tag name", "iframe")
    elem.extend( driver.find_elements("tag name", "frame") )

    for el in elem:
        try:
            src = None
            i = None

            if el.get_attribute("src"):
                src = el.get_attribute("src")
            if el.get_attribute("id"):
                i = el.get_attribute("i")

            current_frame = Classes.Iframe(i, src)
            if current_frame == target_frame:
                driver.switch_to.frame(el)
                return True

        except StaleElementReferenceException as e:
            logging.error("Stale pasta in from action")
            return False
        except Exception as e:
            logging.error("Unhandled error: " + str(e))
            return False
    return False

def find_login_form(driver, graph, early_state=False):
    forms = extract_forms(driver)
    for form in forms:
        for form_input in form.inputs:
            if form_input.itype == "password":
                max_input_for_login = 10
                if len(form.inputs) > max_input_for_login:
                    logging.info("Too many inputs for a login form, " + str(form))
                    continue

                # We need to make sure that the form is part of the graph
                #if early_state or (form in [edge.value.method_data for edge in graph.edges if edge.value.method == "form"]):

                logging.info("NEED TO LOGIN FOR FORM: " + str(form))
                return form
                # else:
                #     print("Need to add form first")


def linkrank(link_edges, visited_list, only_urls=False):
    """ Breadth first search """
    tups = []
    for edge in link_edges:
        if only_urls:
            url = edge
        else:
            url = edge.n2.value.url
        purl = urlparse(url)

        # Higher score => Lower prio
        score = 0

        queries = purl.query.split("&")

        # Long in general => Lower prio
        score += len(url)*0.1

        # More queries => Lower prio
        n_queries = len(queries)*3
        score += n_queries

        for query in queries:
            if "=" in query:
                parts = query.split("=")
                if len(parts) == 2:
                    if parts[1].isnumeric():
                        # Numeric query values => Lower prio
                        score += 3

        # Path depth => Lower prio
        n_depth = len(purl.path.split("/"))
        score += n_depth

        # Fragments (#) => Lower prio
        if purl.fragment:
            score += 5

        # If the path is already visited (but no queries for example).
        if purl.path in visited_list:
            score += 2

        tups.append( (edge, score) )

    tups.sort(key = operator.itemgetter(1))

    return [edge for (edge, _) in tups]


def test_linkrank():
    edges = ["http://example.com/",
             "http://example.com/calc.php?x=123&y=543",
             "http://example.com/calc.php?page=edit",
             "http://example.com/calc.php",
             "http://example.com/news.php",
             "http://example.com/news.php#loweranchor",
             "http://example.com/news.php#upperanchor",
             "http://example.com/news.php?func=view&id=5",
             "http://example.com/news.php?func=view"
             ]

    edges = ["http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=StylesheetPostCompile", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=created_date&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_version&type=function", "http://localhost/cmsms/admin/index.php?section=layout&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/moduleinterface.php?mact=FilePicker,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddUserDefinedTagPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=module_available&type=function", "http://localhost/cmsms/admin/addgroup.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listusers.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=last_modified_by&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditTemplatePost", "http://localhost/cmsms/admin/moduleinterface.php?mact=FileManager,m1_,admin_settings,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=LostPasswordReset", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ModuleInstalled", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=root_url&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ModuleUninstalled", "http://localhost/cmsms/index.php?page=menu-manager", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentEditPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Search&event=SearchAllItemsDeleted", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=FileManager&event=OnFileDeleted", "http://localhost/cmsms/index.php?page=cssmenu_vertical", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Search&event=SearchItemAdded", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddTemplateTypePre", "http://localhost/cmsms/admin/moduleinterface.php?mact=MicroTiny,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "", "http://localhost/cmsms/admin/index.php?section=content&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteDesignPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteGroupPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddUserPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=News&event=NewsCategoryEdited", "http://localhost/cmsms/index.php?page=cssmenu_horizontal", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=LogoutPost", "http://localhost/cmsms/admin/listgroups.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/moduleinterface.php?mact=FilePicker,m1_,edit_profile,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/changegroupperm.php", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_pageoptions&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=setlist&type=function", "http://localhost/cmsms/index.php?mact=News,cntnt01,default,0&cntnt01summarytemplate=Simplex%20News%20Summary&cntnt01number=2&cntnt01detailtemplate=Simplex%20News%20Detail&cntnt01category_id=1&cntnt01returnid=1", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ChangeGroupAssignPost", "http://localhost/cmsms/admin/moduleinterface.php?mact=News,m1_,admin_settings,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/moduleinterface.php?mact=FileManager,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=file_url&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=FileManager&event=OnFileDeleted", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_textarea&type=function", "http://localhost/cmsms/admin/index.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Search&event=SearchItemDeleted", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddGroupPre", "http://localhost/cmsms/admin/listbookmarks.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=root_url&type=function", "http://localhost/cmsms/index.php?page=extensions", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=breadcrumbs&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=News&event=NewsArticleAdded", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=get_template_vars&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=created_date&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditDesignPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteUserDefinedTagPre", "http://localhost/cmsms/admin/moduleinterface.php?mact=News,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=StylesheetPostRender", "http://localhost/cmsms/admin/index.php?section=usersgroups&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ModuleUpgraded", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteUserPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=thumbnail_url&type=function", "http://localhost/cmsms/index.php?page=top_left#menu_vert", "http://localhost/cmsms/admin/moduleinterface.php?mact=AdminSearch,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=CmsJobManager&event=CmsJobManager::OnJobFailed", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=LoginFailed", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Search&event=SearchInitiated", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=FileManager&event=OnFileUploaded", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentPostCompile", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddStylesheetPost", "http://localhost/cmsms/index.php?page=ncleanblue#menu_vert", "http://localhost/cmsms/admin/editusertag.php?__c=2e5eb72b55d92302d32&userplugin_id=2", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=module_available&type=function", "http://localhost/cmsms/admin/adduser.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddTemplateTypePre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=TemplatePostCompile", "http://localhost/cmsms/index.php?page=module-manager", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=description&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=tab_end&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=TemplatePreCompile", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_lang_info&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=browser_lang&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteGroupPost", "http://localhost/cmsms/admin/changegroupassign.php?__c=2e5eb72b55d92302d32&group_id=2", "http://localhost/cmsms/index.php?mact=News,cntnt01,detail,0&cntnt01articleid=1&cntnt01origid=19&cntnt01returnid=24", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddDesignPost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteTemplateTypePre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=redirect_url&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=StylesheetPostRender", "http://localhost/cmsms/admin/adminlog.php?__c=2e5eb72b55d92302d32&clear=true", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ModuleUpgraded", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteTemplateTypePost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=menu_text&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddDesignPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=process_pagedata&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=tab_start&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Search&event=SearchCompleted", "http://localhost/cmsms/admin/adduser.php", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=get_template_vars&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteUserPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditUserDefinedTagPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddDesignPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=LoginPost", "http://localhost/cmsms/admin/index.php?section=extensions&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=image&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentPreCompile", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteDesignPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=description&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Search&event=SearchInitiated", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ModuleUninstalled", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=share_data&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddTemplatePost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddUserDefinedTagPre", "http://localhost/cmsms/admin/editgroup.php?__c=2e5eb72b55d92302d32&group_id=1", "http://localhost/cmsms/index.php?page=microtiny", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=TemplatePostCompile", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentEditPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddUserDefinedTagPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentEditPost", "http://localhost/cmsms/index.php", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=TemplatePreCompile", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=LogoutPost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=News&event=NewsArticleDeleted", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=content&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditUserDefinedTagPost", "http://localhost/cmsms/index.php?page=news", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=page_image&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=summarize&type=modifier", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentPostRender", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=tab_header&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddUserPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Search&event=SearchItemDeleted", "http://localhost/cmsms/admin/changegroupperm.php?__c=2e5eb72b55d92302d32&group_id=2", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=cms_version&type=function", "http://localhost/cmsms/admin/addbookmark.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=recently_updated&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=browser_lang&type=function", "http://localhost/cmsms/admin/", "http://localhost/cmsms/admin/edituser.php?__c=2e5eb72b55d92302d32&user_id=1", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_action_url&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=form_start&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditTemplateTypePost", "http://localhost/cmsms/admin/index.php?section=siteadmin&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_set_language&type=function", "http://localhost/cmsms/admin/editusertag.php?__c=2e5eb72b55d92302d32&userplugin_id=1", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=CmsJobManager&event=CmsJobManager::OnJobFailed", "http://localhost/cmsms/admin/deletegroup.php?__c=2e5eb72b55d92302d32&group_id=3", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentDeletePre", "http://localhost/cmsms/admin/changegroupassign.php?__c=2e5eb72b55d92302d32&group_id=3", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddStylesheetPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_stylesheet&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=TemplatePreFetch", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=form_end&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Search&event=SearchAllItemsDeleted", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=metadata&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddTemplatePost", "http://localhost/cmsms/admin/login.php", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=cms_stylesheet&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=dump&type=function", "http://localhost/cmsms/index.php?page=theme-manager", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentPostCompile", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentDeletePost", "http://localhost/cmsms/index.php?page=cms_tags", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=News&event=NewsCategoryAdded", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ChangeGroupAssignPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_get_language&type=function", "http://localhost/cmsms/index.php?page=default_templates", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_module_hint&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=site_mapper&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddTemplateTypePost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=localedate_format&type=modifier", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteGroupPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=content_module&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteStylesheetPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=setlist&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentPreRender", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddUserPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteUserPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteDesignPost", "http://localhost/cmsms/index.php?mact=News,cntnt01,default,0&cntnt01number=3&cntnt01detailpage=24&cntnt01category_id=1&cntnt01returnid=24", "http://localhost/cmsms/index.php?page=higher-end", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteStylesheetPost", "http://localhost/cmsms", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_module&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=cms_module&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteTemplateTypePost", "http://localhost/cmsms/admin/moduleinterface.php?mact=CMSContentManager,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/index.php?mact=News,cntnt01,detail,0&cntnt01articleid=1&cntnt01detailtemplate=Simplex%20News%20Detail&cntnt01returnid=1", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=SmartyPostCompile", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteStylesheetPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=anchor&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentPostRender", "http://localhost/cmsms/admin/addgroup.php", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=StylesheetPreCompile", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=uploads_url&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditGroupPost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteTemplatePre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditTemplateTypePost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_date_format&type=modifier", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=current_date&type=function", "http://localhost/cmsms/index.php?page=how-cmsms-works", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=page_image&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteTemplatePost", "/cmsms/admin/checksum.php", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditUserDefinedTagPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditTemplatePost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=page_attr&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_yesno&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=sitename&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditTemplateTypePre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditStylesheetPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=StylesheetPreCompile", "http://localhost/cmsms/index.php?page=search", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=News&event=NewsArticleEdited", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditStylesheetPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=admin_icon&type=function", "http://localhost/cmsms/admin/checksum.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_versionname&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteTemplatePost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=repeat&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteStylesheetPre", "http://localhost/cmsms/index.php?page=top_left#main", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=cms_versionname&type=function", "http://localhost/cmsms/admin/changegroupassign.php", "http://localhost/cmsms/index.php?page=menu-manager-2", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=LostPassword", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteUserPost", "http://localhost/cmsms/admin/moduleinterface.php?mact=CMSContentManager,m1_,admin_settings,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteDesignPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=image&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_selflink&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=cms_init_editor&type=function", "http://localhost/cmsms/index.php?page=tags", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditDesignPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_escape&type=modifier", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentPreCompile", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=LostPasswordReset", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=News&event=NewsCategoryAdded", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=News&event=NewsCategoryEdited", "http://localhost/cmsms/admin/myaccount.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ChangeGroupAssignPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=relative_time&type=modifier", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditStylesheetPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=News&event=NewsArticleEdited", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=title&type=function", "http://localhost/cmsms/index.php?page=ncleanblue#main", "http://localhost/cmsms/admin/listusertags.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditUserPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=LostPassword", "http://localhost/cmsms/index.php?page=event-manager", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddTemplatePre", "http://localhost/cmsms/admin/moduleinterface.php?mact=Search,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/siteprefs.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditTemplatePre", "http://localhost/cmsms/admin/changegroupperm.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/adminlog.php?__c=2e5eb72b55d92302d32&download=1", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteTemplatePre", "http://localhost/cmsms/admin/moduleinterface.php?mact=ModuleManager,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32&m1_modulehelp=FilePicker", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Search&event=SearchCompleted", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddGroupPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteUserDefinedTagPost", "http://localhost/cmsms/admin/systeminfo.php?__c=2e5eb72b55d92302d32&cleanreport=1", "http://localhost/cmsms/admin", "http://localhost/cmsms/", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=StylesheetPostCompile", "http://localhost/cmsms/admin/deletegroup.php?__c=2e5eb72b55d92302d32&group_id=2", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=page_attr&type=function", "http://localhost/cmsms/admin/systemmaintenance.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/deleteuserplugin.php?__c=2e5eb72b55d92302d32&userplugin_id=1", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentDeletePre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddStylesheetPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ContentEditPre", "http://localhost/cmsms/admin/moduleinterface.php?mact=DesignManager,m1_,admin_settings,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/changegroupassign.php?__c=2e5eb72b55d92302d32&group_id=1", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=SmartyPreCompile", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=localedate_format&type=modifier", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditStylesheetPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=SmartyPostCompile", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=page_selector&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddDesignPre", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=AddStylesheetPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_jquery&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteTemplateTypePre", "http://localhost/cmsms/#main", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditTemplateTypePre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentDeletePost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=last_modified_by&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=global_content&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=DeleteGroupPost", "http://localhost/cmsms/index.php?page=welcome-to-simplex", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditGroupPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_filepicker&type=function", "http://localhost/cmsms/admin/editusertag.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddUserPost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddTemplateTypePost", "http://localhost/cmsms/index.php?page=top_left", "http://localhost/cmsms/index.php?page=navleft", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteUserDefinedTagPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_help&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ModuleInstalled", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_html_options&type=function", "http://localhost/cmsms/admin/systeminfo.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=TemplatePreFetch", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddGroupPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditUserPost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=News&event=NewsCategoryDeleted", "http://localhost/cmsms/index.php?page=ncleanblue", "http://localhost/cmsms/admin/login.php?forgotpw=1", "http://localhost/cmsms/admin/changegroupperm.php?__c=2e5eb72b55d92302d32&group_id=1", "http://localhost/cmsms/index.php?page=cms_tags-2", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditUserDefinedTagPre", "http://localhost/cmsms/admin/moduleinterface.php?mact=ModuleManager,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=page_error&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=recently_updated&type=function", "http://localhost/cmsms/#nav", "http://localhost/cmsms/index.php?page=templates-and-stylesheets", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=DeleteUserDefinedTagPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditDesignPost", "http://localhost/cmsms/admin/deleteuserplugin.php?__c=2e5eb72b55d92302d32&userplugin_id=2", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=title&type=function", "http://localhost/cmsms/admin/listusers.php", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditUserPost", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=ChangeGroupAssignPost", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddTemplatePre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=sitename&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=modified_date&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=SmartyPreCompile", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=FileManager&event=OnFileUploaded", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=LoginPost", "http://localhost/cmsms/admin/editgroup.php?__c=2e5eb72b55d92302d32&group_id=3", "http://localhost/cmsms/admin/editgroup.php?__c=2e5eb72b55d92302d32&group_id=2", "http://localhost/cmsms/index.php?page=workflow", "http://localhost/cmsms/index.php?page=minimal-template", "http://localhost/cmsms/index.php?page=content", "http://localhost/cmsms/index.php?page=shadowmenu-tab-2-columns", "http://localhost/cmsms/admin/editusertag.php", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=page_warning&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_admin_user&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=News&event=NewsArticleDeleted", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=News&event=NewsCategoryDeleted", "http://localhost/cmsms/admin/#", "http://localhost/cmsms/admin/adminlog.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/moduleinterface.php?mact=CmsJobManager,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/index.php?page=user-defined-tags", "http://localhost/cmsms/admin/changegroupassign.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/index.php?page=default-extensions", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditDesignPre", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=dump&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=menu_text&type=function", "http://localhost/cmsms/index.php?page=where-do-i-get-help", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=metadata&type=function", "http://localhost/cmsms/admin/index.php?section=myprefs&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=ContentPreRender", "http://localhost/cmsms/index.php?page=pages-and-navigation", "http://localhost/cmsms/index.php?mact=News,cntnt01,detail,0&cntnt01articleid=1&cntnt01origid=14&cntnt01returnid=24", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=News&event=NewsArticleAdded", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=LoginFailed", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddUserDefinedTagPost", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=current_date&type=function", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditGroupPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditTemplatePre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=AddGroupPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32&action=showeventhelp&module=Core&event=EditUserPre", "http://localhost/cmsms/admin/eventhandlers.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=redirect_page&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginabout&plugin=modified_date&type=function", "http://localhost/cmsms/admin/moduleinterface.php?mact=DesignManager,m1_,defaultadmin,0&__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=content_image&type=function", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=uploads_url&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Core&event=EditGroupPre", "http://localhost/cmsms/admin/logout.php?__c=2e5eb72b55d92302d32", "http://localhost/cmsms/admin/listtags.php?__c=2e5eb72b55d92302d32&action=showpluginhelp&plugin=cms_init_editor&type=function", "http://localhost/cmsms/admin/editevent.php?__c=2e5eb72b55d92302d32&action=edit&module=Search&event=SearchItemAdded", "http://localhost/cmsms/admin/changegroupperm.php?__c=2e5eb72b55d92302d32&group_id=3", "http://localhost/cmsms/index.php?page=modules"]


    lr = linkrank(edges, [], True)
    for l in lr:
        print(l)

    print(json.dumps(lr))

# test_linkrank()
# exit()


def new_files(link_edges, visited_list):
    tups = []
    for edge in link_edges:
        url = edge.n2.value.url
        purl = urlparse(edge.n2.value.url)
        path = purl.path

        if path not in visited_list:
            print("New file/path: ", path)

        tups.append( (edge, (path in visited_list, path)) )

    tups.sort(key = operator.itemgetter(1))

    return [edge for (edge, _) in tups]


def has_csrf(form):
    # Very heuristic, could be improved perhaps by looking at entropy
    token = False
    for form_input in form.inputs:
        if form_input.name and ("token" in form_input.name or "nonce" in form_input.name):
            token = True
            print(form_input, "is CSRF protection")
    return (not token)

# Returns None if the string is empty, otherwise just the string
def empty2none(s):
    if not s:
        return None
    else:
        return s


def matching_input_to_form(input_element, forms):
    input_type = input_element.get_attribute("type")
    input_name = input_element.get_attribute("name")

    for form in forms:
        for i in form.inputs:
            print("MATCHING", i.itype, input_type, "\t", i.name , input_name)
            if i.itype == input_type and i.name == input_name:
                return (form, i)



