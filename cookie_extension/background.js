chrome.browserAction.setBadgeBackgroundColor({ color: [255, 0, 0, 255] });
chrome.browserAction.setBadgeText({text: 'background'});


function cookie_function(tab) {
  var content = "";
  var downloadable = "";
  var popup = "";

  var domain = getDomain2(tab)
  chrome.cookies.getAll({}, function(cookies) {
    for (var i in cookies) {
      var cookie = cookies[i];
      // if (cookie.domain.indexOf(domain) != -1) {
      content += escapeForPre(cookie.domain);
      content += "\t";
      content += escapeForPre((!cookie.hostOnly).toString().toUpperCase());
      content += "\t";
      content += escapeForPre(cookie.path);
      content += "\t";
      content += escapeForPre(cookie.secure.toString().toUpperCase());
      content += "\t";
      content += escapeForPre(cookie.expirationDate ? Math.round(cookie.expirationDate) : "0");
      content += "\t";
      content += escapeForPre(cookie.name);
      content += "\t";
      content += escapeForPre(cookie.value);
      content += "\n";
      // }
    }
    downloadable += "# HTTP Cookie File for domains related to " + escapeForPre(domain) + ".\n";
    downloadable += "# Downloaded with cookies.txt Chrome Extension (" + escapeForPre("https://chrome.google.com/webstore/detail/njabckikapfpffapmjgojcnbfjonfjfg") + ")\n";
    downloadable += "# Example:  wget -x --load-cookies cookies.txt " + escapeForPre(tab.url) + "\n";
    downloadable += "#\n";

    var uri = "data:application/octet-stream;base64,"+btoa(downloadable + content);
    var a = '<a href='+ uri +' download="cookies.txt">downloaded</a>';

    popup += "# HTTP Cookie File for domains related to <b>" + escapeForPre(domain) + "</b>.\n";
    popup += "# This content may be "+ a +" or pasted into a cookies.txt file and used by wget\n";
    popup += "# Example:  wget -x <b>--load-cookies cookies.txt</b> " + escapeForPre(tab.url) + "\n";
    popup += "#\n";

    document.write("<pre>\n"+ popup + content + "</pre>");

    // https://stackoverflow.com/questions/4845215/making-a-chrome-extension-download-a-file
    // toString(2): binary to string
    // var blob = new Blob([downloadable+content.toString(2)], {type: "text/plain"});
    var blob = new Blob([downloadable+content.toString()], {type: "text/binary"});
    var url = URL.createObjectURL(blob);
    chrome.downloads.download({
      url: url, // The object URL can be used as download URL
      filename: "cookies.txt",
    });
  })
}

function escapeForPre(text) {
  return String(text).replace(/&/g, "&amp;")
                     .replace(/</g, "&lt;")
                     .replace(/>/g, "&gt;")
                     .replace(/"/g, "&quot;")
                     .replace(/'/g, "&#039;");
}

function getDomain2(tab) {
  return new URL(tab.url).hostname;
}

// https://stackoverflow.com/questions/6497548/chrome-extension-make-it-run-every-page-load
chrome.tabs.onUpdated.addListener( function (tabId, changeInfo, tab) {
    if (changeInfo.status == 'complete') {
        // var blob = new Blob(["hello"], {type: "text/binary"});
        // var url = URL.createObjectURL(blob);
        // chrome.downloads.download({
        //   url: url, // The object URL can be used as download URL
        //   filename: "cookies.txt",
        // });
        cookie_function(tab);
    }
  });