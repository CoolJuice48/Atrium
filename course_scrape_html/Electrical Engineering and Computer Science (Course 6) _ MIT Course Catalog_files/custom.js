function getElementsByClassName(className, tag) {
	var ret = [];
	if (document.getElementsByClassName) {
		var els = document.getElementsByClassName(className);
		var nodere = (tag)? new RegExp("\\b" + tag + "\\b", "i") : null;
		for(var i=0; i < els.length; i++) {
			if(nodere.test(els[i].nodeName)) {
				ret[ret.length] = els[i];
			}
		}
	} else {

		var els = document.getElementsByTagName(tag);
		for(var i=0; i < els.length; i++) {
			if(els[i].className == className)
				ret[ret.length] = els[i];
		}
	}
	return ret;
}
function showNav() {
	var els = getElementsByClassName("topnav", "a");
	for(var i=0; i < els.length; i++) {
		els[i].style.display = "block";
	}
}
function hideNav() {
	var els = getElementsByClassName("topnav", "a");
	for(var i=0; i < els.length; i++) {
		els[i].style.display = "none";
	}
}
function loaded() {
	if(window.location.hash.length > 0 && window.location.hash != "#top" && window.location.hash != "top")
		showNav();
	else
		hideNav();
}

$(document).ready(function(){

	//Accessibility helper
    $('.noscript').removeClass('noscript');

    //Show menu when focused
    $('.accessible li a').focus(function() {$('.accessible').addClass('noscript');});
    $('.accessible li a').blur(function() {$('.accessible').removeClass('noscript');});

    //To Top
    $('a#totop').hide();
    $(window).scroll(function() {
        if($(this).scrollTop() != 0) {
            $('a#totop').fadeIn();
        } else {
            $('a#totop').fadeOut();
        }
    });

    //Sidebar header navigation toggle
    $("#sidebar-header").click(function() {
    	if($(window).width() < 805) {
    		$("#cl-menu").slideToggle("fast");
    	}
    });

    var querywidth = 805 - (window.innerWidth - $('body').width());
    function checkWidth(){
        if ($(window).width() <= querywidth) {
            $('#cl-menu').hide();
            $('#section-anchors ul').hide();
            bubblewidth = '100%';
        } else {
            $('#cl-menu').show();
            $('#section-anchors ul').show();
            bubblewidth = '450';
        }
    }

    //Execute on load
    checkWidth();

    //Bind
    var width = $(window).width();
    $(window).resize(function() {
        if($(window).width() != width) {
            checkWidth();
        }
    });

    //Code for nav headers and collapsable degree charts sections
    //wrap each section of <li> in a container to group
    $("li.navheader").each(function() {
        $(this).nextUntil('li.navheader').wrapAll('<ul class="navsub"></ul>');
    });

    $("li.navheader + ul.navsub").hide();

    //toggle the group when navheader is clicked
    $("li.navheader").click(function() {
        $(this).next("ul.navsub").slideToggle("fast");
        $(this).toggleClass("open");
    });

    // if you're on a page within a group, expand the group
    $("li.navheader + ul.navsub > li.self").each(function() {
        $(this).parent("ul.navsub").show();
        $(this).parent("ul.navsub").prev("li.navheader").addClass("open");
		$(this).parent("ul.navsub").prev("li.navheader").addClass("active");
    });

    $("#cl-menu li").each(function() {
        if($(this).hasClass("active")) {
            $(this).children("a").attr("aria-expanded","true");
        }
    });

    //detect currently active and apply open class to button
    $("#cl-menu li.active").children(".toggle-wrap").children("button").addClass("open");
    $("#cl-menu li.active").children(".toggle-wrap").children("button").attr("aria-expanded","true");
    $("#cl-menu li.active").children("ul.nav").attr("aria-hidden","false");

    // add span to (course) text
    $("ul.nav li a").each(function() {
        var linktitle = $(this).text();
        if(linktitle.indexOf("(") >= 0) {
            var rgx = /\(([^)]+)\)/;
            linktitle = linktitle.replace(rgx,"<span class='course-code'>($1)</span>");
            $(this).html(linktitle);
        }
    });

    //show course section list
    $("#select-subject").click(function() {
        $("#section-anchors ul").slideToggle("fast");
    });

    $("#cl-menu ul.levelone li").each(function() {
        if($(this).children(".toggle-wrap").children("a").text() == "Summer") {
            $(this).hide();
        }
    })

    //hide non-summer level - do it here since getTOC doesn't support it
    $("body.summer #cl-menu ul.levelzero > li:not(.active)").hide();
	
	// helper function to maintain accessibility when hiding table header rows
	cla11yjs_hidden_table_headers('#content');

});

function toggleNav(that) {
    $(that).parent().next("ul.nav").slideToggle();
    if($(that).parent().next("ul.nav").attr("aria-hidden") == "false") {
        $(that).parent().next("ul.nav").attr("aria-hidden","true");
    } else {
        $(that).parent().next("ul.nav").attr("aria-hidden","false");
    }

    if($(that).attr("aria-expanded") == "false") {
        $(that).attr("aria-expanded","true");
    } else {
        $(that).attr("aria-expanded","false");
    }

    if(!$(that).hasClass("open")) {
        $(that).parent().next("ul.nav").children("li:first-child").children("a").focus();
    }
    $(that).toggleClass("open");
}
function cla11yjs_hidden_table_headers(x) {
	// hide table cell content without affecting table dom for screen readers
	if (x && x.length >= 1){
		$(x + " table").each(function() {
			var thistext;
			
			$(this).addClass('hide-thead');

			$("caption.hidden").each(function() {
				//update caption
				thistext = $(this).text();
				$(this)
					.html("<span class='sr-only'>" + thistext + "</span>")
					// remove css that is causeing markup semantics to fail screen readers
					.removeClass("hidden");
					// removes css that causes table semantics to fail
			});

			$("tr.hidden").each(function() {
				//update hidden th cells
				$(this)
					.children()
					.each(function() {
						thistext = $(this).text();
						$(this).html("<span class='sr-only'>" + thistext + "</span>");
						// move text to off screen element
					});
					$(this).removeClass("hidden").addClass("cl-a11y-js-cell-reset");
					// remove css that is causeing markup semantics to fail screen readers
					$("head").append(
						"<style>\n" + 
						".page_content table,\n" + 
						"#content table{\n" + 
						"width:100%\n}\n" + 
						".page_content table tr.cl-a11y-js-cell-reset th, \n" + 
						"#content table tr.cl-a11y-js-cell-reset th {\n" +
						"padding:0;\n" +
						"border:none;\n" + 
						" background:none;\n" + 
						"color:#000\n}" + 
						"\n" +
						"</style>");
					// add to head to to support above changes
					
			});
		});
		
		// for MIT. clone table border top styling to tbody when thead is hidden accessibly
		$('table.hide-thead tbody')
			.css("border-top-width", $('#content table').css("border-top-width"))
			.css("border-top-color", $('#content table').css("border-top-color"))
			.css("border-top-style", $('#content table').css("border-top-style"));
		$('#content table').css("border-top","none");
	}
}